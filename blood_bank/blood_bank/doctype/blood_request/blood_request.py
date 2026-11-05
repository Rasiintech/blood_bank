# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from blood_bank.utils import get_patient_blood_group, set_patient_blood_group, update_unit


class BloodRequest(Document):
	def validate(self):
		on_file = get_patient_blood_group(self.patient)
		if on_file and not self.patient_blood_group:
			self.patient_blood_group = on_file
		elif on_file and self.patient_blood_group != on_file:
			frappe.throw(_("Patient is recorded as {0}, not {1}").format(on_file, self.patient_blood_group), title=_("Blood Group Mismatch"))
		if not self.inpatient_record and self.docstatus == 0:
			from blood_bank.billing import current_admission
			self.inpatient_record = current_admission(self.patient)
		if not (self.practitioner or self.external_practitioner):
			frappe.throw(_("Enter the ordering doctor (or External Doctor for referred patients)"))
		seen = set()
		for row in self.items:
			if cint(row.units_required) <= 0:
				frappe.throw(_("Row {0}: units must be at least 1").format(row.idx))
			if row.component in seen:
				frappe.throw(_("Row {0}: {1} is listed twice").format(row.idx, row.component))
			seen.add(row.component)
		if self.docstatus == 0:
			self.status = "Draft"

	def on_submit(self):
		if self.patient_blood_group:
			set_patient_blood_group(self.patient, self.patient_blood_group)
		from blood_bank.billing import billing_mode_for, reconcile
		self.db_set("billing_mode", billing_mode_for(self), update_modified=False)
		self.update_counts_and_status()
		reconcile(self, reference=self)

	def onload(self):
		if self.docstatus == 1 and self.status != "Cancelled":
			from blood_bank.billing import expected_charges, charged_so_far
			want, have = expected_charges(self), charged_so_far(self)
			self.set_onload("charges_pending", any(abs(want.get(k, 0) - have.get(k, 0)) > 0 for k in set(want) | set(have)))
		self.set_onload("xm_components", [r.component for r in self.items
			if cint(frappe.db.get_value("Blood Component", r.component, "requires_crossmatch"))])

	@frappe.whitelist()
	def get_lab_values(self):
		from blood_bank.lab import latest_patient_values
		v = latest_patient_values(self.patient)
		if v["hb"] is not None:
			self.hb_g_dl = v["hb"]
		if v["platelets"] is not None:
			self.platelet_count = v["platelets"]
		self.lab_values_from = "; ".join(v["sources"])[:140] or None
		return v

	@frappe.whitelist()
	def suggest_replacement_donors(self):
		return suggested_donors(self.items)

	def on_cancel(self):
		issued = frappe.get_all("Blood Unit", filters={"blood_request": self.name, "status": ["in", ["Issued", "Transfused"]]}, pluck="name")
		if issued:
			frappe.throw(_("Units already issued for this request: {0}").format(", ".join(issued)))
		for name in frappe.get_all("Blood Unit", filters={"blood_request": self.name, "status": "Reserved"}, pluck="name"):
			update_unit(name, status="Available", reserved_for=None, blood_request=None, crossmatch=None, reserved_until=None)
		self.db_set("status", "Cancelled")
		from blood_bank.billing import reconcile
		self.reload()
		reconcile(self, reference=self)

	def update_counts_and_status(self):
		units = frappe.get_all("Blood Unit", filters={"blood_request": self.name}, fields=["component", "status"])
		total = dict(req=0, res=0, iss=0, tr=0)
		for row in self.items:
			mine = [u for u in units if u.component == row.component]
			res = len([u for u in mine if u.status == "Reserved"])
			iss = len([u for u in mine if u.status in ("Issued", "Transfused")])
			tr = len([u for u in mine if u.status == "Transfused"])
			row.db_set({"units_reserved": res, "units_issued": iss, "units_transfused": tr}, update_modified=False)
			total["req"] += cint(row.units_required)
			total["res"] += res
			total["iss"] += iss
			total["tr"] += tr
		donations = frappe.db.count("Blood Donation", {"blood_request": self.name, "docstatus": 1})
		if self.docstatus == 2:
			status = "Cancelled"
		elif self.status == "Closed" or frappe.db.get_value("Blood Request", self.name, "status") == "Closed":
			status = "Closed"
		elif total["req"] and total["tr"] >= total["req"]:
			status = "Completed"
		elif total["req"] and total["iss"] >= total["req"]:
			status = "Issued"
		elif total["iss"]:
			status = "Partially Issued"
		elif total["res"]:
			status = "Crossmatched"
		elif cint(self.replacement_donors_needed) > donations:
			status = "Awaiting Donor"
		else:
			status = "Requested"
		was = frappe.db.get_value("Blood Request", self.name, "status")
		values = {"status": status, "replacement_donations": donations}
		if status == "Completed" and not self.closed_on:
			values["closed_on"] = frappe.utils.now_datetime()
			values["close_reason"] = "All units transfused"
		self.db_set(values, update_modified=False)
		self.status = status
		if status == "Completed" and was != "Completed":
			# On Request: credit what was prepaid but not used
			from blood_bank.billing import reconcile
			reconcile(frappe.get_doc("Blood Request", self.name))


def suggested_donors(items):
	"""One bag per donor. Red cells (Whole Blood / Red Cells) each need their own bag; plasma and platelets
	come from the same split bags, so the largest of the three groups decides."""
	import math
	from blood_bank.utils import setting

	red = plasma = plt = 0
	for row in items or []:
		abbr = frappe.db.get_value("Blood Component", row.get("component"), "abbreviation") if row.get("component") else None
		units = cint(row.get("units_required"))
		if abbr in ("WB", "RBC"):
			red += units
		elif abbr in ("FFP", "PL"):
			plasma += units
		else:
			plt += units
	per_unit = frappe.utils.flt(setting("replacement_donors_per_unit"))
	return int(math.ceil(max(red, plasma, plt) * per_unit))
