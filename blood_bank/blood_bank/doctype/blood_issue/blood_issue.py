# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from blood_bank.billing import validate_payment_for_issue
from blood_bank.utils import OFFICER, check_compatibility, update_unit


class BloodIssue(Document):
	def validate(self):
		req = frappe.get_doc("Blood Request", self.blood_request)
		if req.docstatus != 1 or req.status in ("Cancelled", "Completed"):
			frappe.throw(_("Blood Request {0} must be submitted and open").format(req.name))
		self.patient = req.patient
		if self.emergency_release:
			if not self.authorised_by:
				frappe.throw(_("Emergency release needs the authorising Blood Bank Officer"))
			if OFFICER not in frappe.get_roles(self.authorised_by) and "System Manager" not in frappe.get_roles(self.authorised_by):
				frappe.throw(_("{0} is not a Blood Bank Officer").format(self.authorised_by))
		seen = set()
		for row in self.items:
			if row.blood_unit in seen:
				frappe.throw(_("Row {0}: unit {1} is listed twice").format(row.idx, row.blood_unit))
			seen.add(row.blood_unit)
			if self.docstatus == 0:
				self.check_unit(row, frappe.get_doc("Blood Unit", row.blood_unit), req)
		if self.docstatus == 0:
			validate_payment_for_issue(req, self.emergency_release)

	def check_unit(self, row, u, req):
		issue_time = get_datetime(self.issue_datetime)
		if get_datetime(u.expiry_datetime) <= issue_time:
			frappe.throw(_("Row {0}: unit {1} has expired").format(row.idx, u.name))
		reserved_here = u.status == "Reserved" and u.reserved_for == self.patient and u.blood_request == req.name
		if reserved_here:
			if u.reserved_until and get_datetime(u.reserved_until) < issue_time:
				frappe.throw(_("Row {0}: crossmatch for unit {1} has expired; crossmatch again").format(row.idx, u.name))
			return
		if not self.emergency_release:
			if u.status == "Reserved":
				frappe.throw(_("Row {0}: unit {1} is reserved for another patient").format(row.idx, u.name), title=_("Wrong Unit"))
			frappe.throw(_("Row {0}: unit {1} is not crossmatched for this patient").format(row.idx, u.name), title=_("Wrong Unit"))
		# Emergency: uncrossmatched unit from stock
		if u.status != "Available":
			frappe.throw(_("Row {0}: unit {1} is {2}").format(row.idx, u.name, u.status))
		if u.test_status not in ("Cleared", "Not Required"):
			frappe.throw(_("Row {0}: unit {1} tests are {2}").format(row.idx, u.name, u.test_status))
		rule = frappe.db.get_value("Blood Component", u.component, "compatibility_rule")
		ok, msg = check_compatibility(rule, req.patient_blood_group, u.blood_group, emergency=True)
		if not ok:
			frappe.throw(_("Row {0}: {1}").format(row.idx, msg), title=_("Not Compatible"))
		if msg:
			frappe.msgprint(_("Row {0}: {1}").format(row.idx, msg), indicator="orange", alert=True)

	def on_submit(self):
		req = frappe.get_doc("Blood Request", self.blood_request)
		for row in self.items:
			update_unit(row.blood_unit, status="Issued", blood_issue=self.name, issued_on=self.issue_datetime,
				blood_request=req.name, reserved_for=self.patient)
		req.update_counts_and_status()
		if self.emergency_release:
			frappe.msgprint(_("Emergency release recorded. Make sure the patient sample is crossmatched as soon as possible."),
				indicator="orange")

	def on_cancel(self):
		for row in self.items:
			u = frappe.get_doc("Blood Unit", row.blood_unit)
			if u.blood_issue != self.name:
				continue
			if u.status != "Issued":
				frappe.throw(_("Unit {0} is already {1}; cannot cancel the issue").format(u.name, u.status))
			if u.crossmatch and u.reserved_until and get_datetime(u.reserved_until) > now_datetime():
				update_unit(u, status="Reserved", blood_issue=None, issued_on=None)
			else:
				update_unit(u, status="Available", blood_issue=None, issued_on=None, reserved_for=None,
					blood_request=None, crossmatch=None, reserved_until=None)
		frappe.get_doc("Blood Request", self.blood_request).update_counts_and_status()


@frappe.whitelist()
def get_reserved_units(blood_request):
	frappe.get_doc("Blood Request", blood_request).check_permission("read")
	return frappe.get_all("Blood Unit", filters={"blood_request": blood_request, "status": "Reserved",
		"reserved_until": [">", now_datetime()]}, fields=["name as blood_unit", "component", "blood_group",
		"expiry_datetime", "crossmatch"], order_by="expiry_datetime asc")
