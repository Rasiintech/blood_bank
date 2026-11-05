# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from blood_bank.lab import fill_crossmatch
from blood_bank.utils import (check_compatibility, get_patient_blood_group, set_patient_blood_group,
	setting, update_unit)

USABLE_TESTS = ("Cleared", "Not Required")


class BloodCrossmatch(Document):
	def validate(self):
		req = frappe.db.get_value("Blood Request", self.blood_request, ["docstatus", "patient", "status", "request_datetime"], as_dict=True)
		if not req or req.docstatus != 1 or req.status in ("Cancelled", "Completed", "Closed"):
			frappe.throw(_("Blood Request {0} must be submitted and open").format(self.blood_request))
		self.patient = req.patient
		on_file = get_patient_blood_group(self.patient)
		if on_file and self.patient_blood_group != on_file:
			frappe.throw(_("Patient is recorded as {0}, not {1}").format(on_file, self.patient_blood_group), title=_("Blood Group Mismatch"))
		components = set(frappe.get_all("Blood Request Item", filters={"parent": self.blood_request}, pluck="component"))
		seen = set()
		for row in self.items:
			if row.blood_unit in seen:
				frappe.throw(_("Row {0}: unit {1} is listed twice").format(row.idx, row.blood_unit))
			seen.add(row.blood_unit)
			u = frappe.get_doc("Blood Unit", row.blood_unit)
			if self.docstatus == 0:
				self.check_unit(row, u, components)
		from blood_bank.utils import check_time_order
		check_time_order([(_("Request"), req.request_datetime), (_("Patient Sample Taken"), self.sample_datetime),
			(_("Crossmatch"), self.crossmatch_datetime)])
		self.valid_until = add_to_date(get_datetime(self.crossmatch_datetime), hours=cint(setting("crossmatch_validity_hours")) or 72)

	def check_unit(self, row, u, components):
		if u.status != "Available" and not (u.status == "Reserved" and u.blood_request == self.blood_request):
			frappe.throw(_("Row {0}: unit {1} is {2}").format(row.idx, u.name, u.status))
		if u.test_status not in USABLE_TESTS:
			frappe.throw(_("Row {0}: unit {1} tests are {2}").format(row.idx, u.name, u.test_status))
		if get_datetime(u.expiry_datetime) <= now_datetime():
			frappe.throw(_("Row {0}: unit {1} has expired").format(row.idx, u.name))
		if u.directed_request and u.directed_request != self.blood_request:
			frappe.throw(_("Row {0}: unit {1} is a directed donation held for {2}").format(row.idx, u.name, u.directed_patient))
		if u.component not in components:
			frappe.throw(_("Row {0}: {1} was not requested").format(row.idx, u.component))
		if not cint(frappe.db.get_value("Blood Component", u.component, "requires_crossmatch")):
			frappe.throw(_("Row {0}: {1} is not crossmatched. Give it at Blood Issue (Get Reserved Units).").format(row.idx, u.component))
		rule = frappe.db.get_value("Blood Component", u.component, "compatibility_rule")
		ok, msg = check_compatibility(rule, self.patient_blood_group, u.blood_group)
		if not ok:
			frappe.throw(_("Row {0}: {1}").format(row.idx, msg), title=_("Not Compatible"))
		if msg:
			frappe.msgprint(_("Row {0}: {1}").format(row.idx, msg), indicator="orange", alert=True)

	@frappe.whitelist()
	def fetch_from_lab(self):
		return fill_crossmatch(self)

	def before_submit(self):
		missing = [str(r.idx) for r in self.items if not r.result]
		if missing:
			frappe.throw(_("Enter the crossmatch result for rows {0}").format(", ".join(missing)))
		if self.verified_by and self.verified_by == self.performed_by:
			frappe.throw(_("Verified By must be a different person"))

	def on_submit(self):
		set_patient_blood_group(self.patient, self.patient_blood_group)
		if not frappe.db.get_value("Blood Request", self.blood_request, "patient_blood_group"):
			frappe.db.set_value("Blood Request", self.blood_request, "patient_blood_group", self.patient_blood_group)
		for row in self.items:
			if row.result != "Compatible":
				continue
			u = frappe.get_doc("Blood Unit", row.blood_unit)
			if u.status != "Available" and u.blood_request != self.blood_request:
				frappe.throw(_("Unit {0} was taken by another document ({1})").format(u.name, u.status))
			update_unit(u, status="Reserved", reserved_for=self.patient, blood_request=self.blood_request,
				crossmatch=self.name, reserved_until=self.valid_until)
		req = frappe.get_doc("Blood Request", self.blood_request)
		req.update_counts_and_status()
		from blood_bank.billing import reconcile
		reconcile(req, reference=self)

	def on_cancel(self):
		for name in frappe.get_all("Blood Unit", filters={"crossmatch": self.name, "status": "Reserved"}, pluck="name"):
			update_unit(name, status="Available", reserved_for=None, blood_request=None, crossmatch=None, reserved_until=None)
		req = frappe.get_doc("Blood Request", self.blood_request)
		req.update_counts_and_status()
		from blood_bank.billing import reconcile
		reconcile(req, reference=self)


@frappe.whitelist()
def get_compatible_units(blood_request, patient_blood_group=None, exclude=None):
	"""Fill the table with the best compatible bags for what still needs a crossmatch (Whole Blood / Red Cells).
	Plasma and platelets are not crossmatched: they are picked at Blood Issue, so they are only reported."""
	from blood_bank.request_summary import compatible_units, needs_crossmatch, patient_group
	req = frappe.get_doc("Blood Request", blood_request)
	req.check_permission("read")
	group = patient_group(req, patient_blood_group)
	if not group:
		frappe.throw(_("Enter the patient's blood group first (from the grouping result)"))
	exclude = set(frappe.parse_json(exclude) if exclude else [])
	out, notes = [], []
	for row in req.items:
		needed = cint(row.units_required) - cint(row.units_reserved) - cint(row.units_issued)
		if needed <= 0:
			continue
		if not needs_crossmatch(row.component):
			notes.append(_("{0} x {1}: no crossmatch, picked at Blood Issue > Get Reserved Units").format(needed, row.component))
			continue
		units = [u for u in compatible_units(req, group, row.component, exclude) if u.status == "Available"]
		if len(units) < needed:
			notes.append(_("{0}: {1} needed, only {2} compatible in stock").format(row.component, needed, len(units)))
		for u in units[:needed]:
			line = {"blood_unit": u.name, "component": u.component, "unit_blood_group": u.blood_group,
				"expiry_datetime": u.expiry_datetime}
			if u.tags:
				line["remarks"] = ", ".join(u.tags)[:140]
			if u.lab_xm and u.lab_xm.crossmatch_result == "Compatible":
				line["result"] = "Compatible"
				line["remarks"] = _("Lab crossmatch {0} ({1})").format(u.lab_xm.crossmatch_lab_value or "Compatible",
					u.lab_xm.lab_reference or u.lab_xm.name)[:140]
			out.append(line)
	return {"units": out, "notes": notes}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def unit_query(doctype, txt, searchfield, start, page_len, filters):
	"""Blood Unit dropdown on the crossmatch: only bags this patient can receive, for requested components that
	need a crossmatch, best first."""
	from blood_bank.request_summary import compatible_units, needs_crossmatch, patient_group
	if not filters.get("blood_request"):
		return []
	req = frappe.get_doc("Blood Request", filters.get("blood_request"))
	group = patient_group(req, filters.get("patient_blood_group"))
	if not group:
		return []
	exclude = set(frappe.parse_json(filters.get("exclude") or "[]"))
	txt = (txt or "").lower()
	rows = []
	for comp in dict.fromkeys(r.component for r in req.items):
		if not needs_crossmatch(comp):
			continue
		for u in compatible_units(req, group, comp, exclude):
			if txt and txt not in u.name.lower() and txt not in (u.blood_group or "").lower():
				continue
			rows.append((u.name, "{0} · {1} · {2} {3}{4}".format(u.component, u.blood_group, _("exp"),
				frappe.utils.format_date(u.expiry_datetime), (" · " + ", ".join(u.tags)) if u.tags else "")))
	start, page_len = cint(start), cint(page_len) or 20
	return rows[start:start + page_len]
