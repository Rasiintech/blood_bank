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
	"""Suggest in-date, cleared, compatible units for what is still needed, earliest expiry first."""
	req = frappe.get_doc("Blood Request", blood_request)
	req.check_permission("read")
	group = patient_blood_group or req.patient_blood_group or get_patient_blood_group(req.patient)
	if not group:
		frappe.throw(_("Enter the patient's blood group first (from the grouping result)"))
	exclude = set(frappe.parse_json(exclude) if exclude else [])
	out = []
	for row in req.items:
		needed = cint(row.units_required) - cint(row.units_reserved) - cint(row.units_issued)
		if needed <= 0:
			continue
		if not cint(frappe.db.get_value("Blood Component", row.component, "requires_crossmatch")):
			continue  # plasma / platelets: issued by group, no crossmatch
		rule = frappe.db.get_value("Blood Component", row.component, "compatibility_rule")
		candidates = frappe.get_all("Blood Unit", filters={"component": row.component, "status": "Available",
			"test_status": ["in", USABLE_TESTS], "expiry_datetime": [">", now_datetime()]},
			fields=["name", "component", "blood_group", "expiry_datetime", "donor_test", "directed_request"], order_by="expiry_datetime asc")
		directed, exact, other = [], [], []
		lab_xm = lab_crossmatches(req.patient)
		for c in candidates:
			if c.name in exclude:
				continue
			ok, msg = check_compatibility(rule, group, c.blood_group)
			if not ok:
				continue
			if c.directed_request and c.directed_request != req.name:
				continue  # held for another patient
			xm = lab_xm.get(c.donor_test)
			if xm and xm.crossmatch_result == "Incompatible":
				continue
			c.lab_xm = xm
			(directed if (xm or c.directed_request == req.name) else exact if c.blood_group == group else other).append(c)
		# the relatives' bags already crossmatched with this patient in the lab first, then same group, then compatible
		for c in (directed + exact + other)[:needed]:
			row = {"blood_unit": c.name, "component": c.component, "unit_blood_group": c.blood_group,
				"expiry_datetime": c.expiry_datetime}
			if c.directed_request == req.name and not c.lab_xm:
				row["remarks"] = _("Directed donation for this patient")
			if c.lab_xm:
				row.update(result="Compatible", remarks=_("Lab crossmatch {0} ({1})").format(
					c.lab_xm.crossmatch_lab_value or "Compatible", c.lab_xm.lab_reference or c.lab_xm.name)[:140])
			out.append(row)
	return out


def lab_crossmatches(patient):
	"""Donor Tests whose lab result already crossmatched the donor with this patient (replacement donors)."""
	if not frappe.get_meta("Blood Donor Test").has_field("crossmatch_result"):
		return {}
	rows = frappe.get_all("Blood Donor Test", filters={"crossmatch_patient": patient, "docstatus": 1,
		"crossmatch_result": ["in", ["Compatible", "Incompatible"]]},
		fields=["name", "crossmatch_result", "crossmatch_lab_value", "lab_reference"])
	return {r.name: r for r in rows}
