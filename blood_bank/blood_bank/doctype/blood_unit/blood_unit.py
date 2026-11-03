# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from blood_bank.utils import OFFICER, has_role, is_expired, update_unit


class BloodUnit(Document):
	def validate(self):
		if not self.is_new() and not self.flags.from_blood_bank:
			for field in ("status", "test_status", "component", "blood_group", "expiry_datetime", "reserved_for", "blood_issue"):
				if self.has_value_changed(field):
					frappe.throw(_("{0} of a blood unit is changed only by blood bank documents").format(self.meta.get_label(field)))
		if not self.blood_group and self.status in ("Available", "Reserved", "Issued", "Transfused"):
			frappe.throw(_("Unit {0} has no blood group").format(self.name))
		if self.is_new() and not self.flags.from_blood_bank:
			frappe.throw(_("Blood Units are created by Blood Donation, Blood Unit Receipt or Component Preparation"))


@frappe.whitelist()
def release_units(units):
	"""Blood Bank Officer releases cleared units from Quarantine to Available."""
	if not has_role(OFFICER):
		frappe.throw(_("Only a Blood Bank Officer can release units"), frappe.PermissionError)
	if isinstance(units, str):
		units = json.loads(units) if units.startswith("[") else [units]
	released, skipped = [], []
	for name in units:
		u = frappe.get_doc("Blood Unit", name)
		if u.status != "Quarantine":
			skipped.append(_("{0}: status is {1}").format(name, u.status))
		elif u.test_status in ("Pending", "Reactive"):
			skipped.append(_("{0}: tests are {1}").format(name, u.test_status))
		elif is_expired(u):
			skipped.append(_("{0}: expired").format(name))
		elif not u.blood_group:
			skipped.append(_("{0}: blood group missing").format(name))
		else:
			values = dict(status="Available", released_by=frappe.session.user, released_on=now_datetime())
			if u.test_status == "On Hold":
				values["test_status"] = "Cleared"
			update_unit(u, **values)
			released.append(name)
	return {"released": released, "skipped": skipped}


@frappe.whitelist()
def move_storage(unit, storage):
	frappe.get_doc("Blood Unit", unit).check_permission("write")
	frappe.db.set_value("Blood Unit", unit, "storage", storage)


@frappe.whitelist()
def hold_unit(unit, reason):
	"""Blood Bank Officer takes an Available bag off the shelf back to Quarantine (undo a release)."""
	if not has_role(OFFICER):
		frappe.throw(_("Only a Blood Bank Officer can put a unit on hold"), frappe.PermissionError)
	if not (reason or "").strip():
		frappe.throw(_("Give the reason for the hold"))
	u = frappe.get_doc("Blood Unit", unit)
	if u.status != "Available":
		frappe.throw(_("Only Available units can be put on hold (this one is {0})").format(u.status))
	note = _("{0}: put on hold by {1}. Reason: {2}").format(frappe.format(now_datetime(), "Datetime"), frappe.session.user, reason.strip())
	update_unit(u, status="Quarantine", test_status="On Hold", released_by=None, released_on=None,
		remarks=((u.remarks or "") + "\n" + note).strip())
	return u.name


@frappe.whitelist()
def release_directed(unit, reason):
	"""Officer: end a directed hold so the bag can go to any compatible patient."""
	from frappe.utils import format_datetime, now_datetime
	if not has_role(OFFICER):
		frappe.throw(_("Only a Blood Bank Officer can release a directed bag"), frappe.PermissionError)
	if not (reason or "").strip():
		frappe.throw(_("Give the reason"))
	u = frappe.get_doc("Blood Unit", unit)
	if not u.directed_request:
		frappe.throw(_("Unit {0} is not held for anyone").format(unit))
	note = _("{0}: directed hold for {1} released by {2}. Reason: {3}").format(
		format_datetime(now_datetime()), u.directed_request, frappe.session.user, reason.strip())
	update_unit(u, directed_request=None, directed_patient=None, remarks=((u.remarks or "") + "\n" + note).strip())
	return u.name
