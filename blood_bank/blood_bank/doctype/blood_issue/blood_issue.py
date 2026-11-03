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
		if req.docstatus != 1 or req.status in ("Cancelled", "Completed", "Closed"):
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
			from blood_bank.utils import check_time_order
			check_time_order([(_("Request"), req.request_datetime), (_("Issue"), self.issue_datetime)])
			validate_payment_for_issue(req, self.emergency_release, [r.blood_unit for r in self.items])

	def check_unit(self, row, u, req):
		issue_time = get_datetime(self.issue_datetime)
		if get_datetime(u.expiry_datetime) <= issue_time:
			frappe.throw(_("Row {0}: unit {1} has expired").format(row.idx, u.name))
		reserved_here = u.status == "Reserved" and u.reserved_for == self.patient and u.blood_request == req.name
		if reserved_here:
			if u.reserved_until and get_datetime(u.reserved_until) < issue_time:
				frappe.throw(_("Row {0}: crossmatch for unit {1} has expired; crossmatch again").format(row.idx, u.name))
			return
		if u.directed_request and u.directed_request != req.name:
			frappe.throw(_("Row {0}: unit {1} is a directed donation held for another patient").format(row.idx, u.name), title=_("Wrong Unit"))
		needs_xm = frappe.db.get_value("Blood Component", u.component, "requires_crossmatch")
		if not needs_xm and not self.emergency_release:
			# plasma / platelets: no crossmatch, a compatible group from stock is enough
			if u.status != "Available":
				frappe.throw(_("Row {0}: unit {1} is {2}").format(row.idx, u.name, u.status))
			if u.test_status not in ("Cleared", "Not Required"):
				frappe.throw(_("Row {0}: unit {1} tests are {2}").format(row.idx, u.name, u.test_status))
			if u.component not in [r.component for r in req.items]:
				frappe.throw(_("Row {0}: {1} was not requested").format(row.idx, u.component))
			rule = frappe.db.get_value("Blood Component", u.component, "compatibility_rule")
			ok, msg = check_compatibility(rule, req.patient_blood_group, u.blood_group)
			if not ok:
				frappe.throw(_("Row {0}: {1}").format(row.idx, msg), title=_("Not Compatible"))
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
		from blood_bank.billing import reconcile
		reconcile(req, reference=self)
		inv = frappe.db.get_value("Blood Request Charge", {"parent": req.name, "reference_name": self.name}, "sales_invoice")
		if inv:
			self.db_set("sales_invoice", inv, update_modified=False)
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
		req = frappe.get_doc("Blood Request", self.blood_request)
		req.update_counts_and_status()
		from blood_bank.billing import reconcile
		reconcile(req, reference=self)


@frappe.whitelist()
def get_reserved_units(blood_request):
	"""Crossmatched bags reserved for the request, plus compatible plasma / platelets still needed (no crossmatch)."""
	req = frappe.get_doc("Blood Request", blood_request)
	req.check_permission("read")
	out = frappe.get_all("Blood Unit", filters={"blood_request": blood_request, "status": "Reserved",
		"reserved_until": [">", now_datetime()]}, fields=["name as blood_unit", "component", "blood_group",
		"expiry_datetime", "crossmatch"], order_by="expiry_datetime asc")
	from frappe.utils import cint
	for row in req.items:
		if cint(frappe.db.get_value("Blood Component", row.component, "requires_crossmatch")):
			continue
		needed = cint(row.units_required) - cint(row.units_issued)
		if needed <= 0 or not req.patient_blood_group:
			continue
		rule = frappe.db.get_value("Blood Component", row.component, "compatibility_rule")
		picked = []
		for u in frappe.get_all("Blood Unit", filters={"component": row.component, "status": "Available",
				"test_status": ["in", ["Cleared", "Not Required"]], "expiry_datetime": [">", now_datetime()]},
				fields=["name", "component", "blood_group", "expiry_datetime", "directed_request"], order_by="expiry_datetime asc"):
			if u.directed_request and u.directed_request != req.name:
				continue
			if check_compatibility(rule, req.patient_blood_group, u.blood_group)[0]:
				picked.append(u)
		picked.sort(key=lambda u: (0 if u.directed_request == req.name else 1 if u.blood_group == req.patient_blood_group else 2))
		out += [{"blood_unit": u.name, "component": u.component, "blood_group": u.blood_group,
			"expiry_datetime": u.expiry_datetime} for u in picked[:needed]]
	return out
