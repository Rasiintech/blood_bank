# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from blood_bank.utils import update_unit

ALLOWED = ("Quarantine", "Available", "Reserved", "Expired", "Issued")


class BloodUnitDiscard(Document):
	def validate(self):
		seen = set()
		for row in self.items:
			if row.blood_unit in seen:
				frappe.throw(_("Row {0}: unit {1} is listed twice").format(row.idx, row.blood_unit))
			seen.add(row.blood_unit)
			status = frappe.db.get_value("Blood Unit", row.blood_unit, "status")
			if self.docstatus == 0:
				row.status_before = status
			if status not in ALLOWED and self.docstatus == 0:
				frappe.throw(_("Row {0}: unit {1} is {2} and cannot be discarded").format(row.idx, row.blood_unit, status))
			if status == "Issued" and row.reason != "Returned Late" and not self.flags.from_blood_bank:
				frappe.throw(_("Row {0}: issued units come back through a Blood Unit Return").format(row.idx))

	def on_submit(self):
		for row in self.items:
			unit = frappe.get_doc("Blood Unit", row.blood_unit)
			values = dict(status="Discarded", blood_unit_discard=self.name, discard_reason=row.reason)
			if row.reason == "Reactive Test":
				values["test_status"] = "Reactive"
			if unit.status == "Reserved":
				values.update(reserved_for=None, crossmatch=None, reserved_until=None)
			req = unit.blood_request
			update_unit(unit, **values)
			if req and frappe.db.get_value("Blood Request", req, "docstatus") == 1:
				frappe.get_doc("Blood Request", req).update_counts_and_status()

	def on_cancel(self):
		for row in self.items:
			status = {"Reserved": "Available", "Issued": "Quarantine"}.get(row.status_before, row.status_before) or "Quarantine"
			update_unit(row.blood_unit, status=status, blood_unit_discard=None, discard_reason=None)


def discard_units(units, reason, source_doc=None, remarks=None):
	"""Create and submit a discard for the given units (used by tests, returns, expiry)."""
	if not units:
		return None
	doc = frappe.new_doc("Blood Unit Discard")
	if source_doc:
		doc.reference_doctype = source_doc.doctype
		doc.reference_name = source_doc.name
	doc.remarks = remarks
	for u in units:
		doc.append("items", {"blood_unit": u, "reason": reason})
	doc.flags.from_blood_bank = True
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
	return doc.name
