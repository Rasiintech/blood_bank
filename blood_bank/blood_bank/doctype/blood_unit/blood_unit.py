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
