# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappe.utils import now_datetime

from blood_bank.utils import (BLOOD_GROUPS, OFFICER, donor_age, get_patient_blood_group, has_role,
	patient_blood_group_field, set_patient_blood_group)


class BloodDonor(Document):
	def validate(self):
		other = frappe.db.get_value("Blood Donor", {"patient": self.patient, "name": ["!=", self.name]})
		if other:
			frappe.throw(_("Patient {0} is already registered as donor {1}").format(self.patient, other), title=_("Duplicate Donor"))
		self.sync_from_patient()

	def sync_from_patient(self):
		"""Keep name, sex, DOB and mobile identical to the Patient record."""
		p = frappe.db.get_value("Patient", self.patient, ["patient_name", "sex", "dob", "mobile"], as_dict=True) or {}
		self.donor_name = p.get("patient_name")
		self.sex = p.get("sex")
		self.date_of_birth = p.get("dob")
		self.mobile_no = p.get("mobile")
		self.age_years = donor_age(self) if self.date_of_birth else None
		on_file = get_patient_blood_group(self.patient)
		if on_file and not self.blood_group:
			self.blood_group = on_file

	def on_update(self):
		if self.blood_group:
			set_patient_blood_group(self.patient, self.blood_group)


@frappe.whitelist()
def get_or_create_donor(patient):
	"""Called from the Patient form: open the donor record for this patient, creating it if needed."""
	frappe.has_permission("Blood Donor", "create", throw=True)
	existing = frappe.db.get_value("Blood Donor", {"patient": patient})
	if existing:
		return existing
	donor = frappe.get_doc({"doctype": "Blood Donor", "patient": patient})
	donor.insert()
	return donor.name


@frappe.whitelist()
def correct_blood_group(donor, blood_group, reason):
	"""Blood Bank Officer corrects a wrong group after a repeat grouping, on the donor and the Patient."""
	if not has_role(OFFICER):
		frappe.throw(_("Only a Blood Bank Officer can correct a blood group"), frappe.PermissionError)
	if blood_group not in BLOOD_GROUPS:
		frappe.throw(_("Choose a valid blood group"))
	if not (reason or "").strip():
		frappe.throw(_("Give the reason (e.g. the repeat grouping Lab Result number)"))
	d = frappe.get_doc("Blood Donor", donor)
	old = d.blood_group or "-"
	if frappe.db.exists("Blood Unit", {"donor": d.name, "status": ["in", ["Quarantine", "Available", "Reserved", "Issued"]]}):
		frappe.throw(_("This donor has bags in stock or issued. Quarantine and re-group those bags before correcting."))
	field = patient_blood_group_field()
	if field and d.patient:
		frappe.db.set_value("Patient", d.patient, field, blood_group)
	note = _("{0}: blood group corrected {1} -> {2} by {3}. Reason: {4}").format(
		frappe.format(now_datetime(), "Datetime"), old, blood_group, frappe.session.user, reason.strip())
	d.blood_group = blood_group
	d.notes = ((d.notes or "") + "\n" + note).strip()
	d.flags.ignore_permissions = True
	d.save()
	return d.blood_group


@frappe.whitelist()
def next_action(donor):
	"""Donor form: an unfinished screening to continue, or why a new one cannot start."""
	from blood_bank.blood_bank.doctype.blood_donation.blood_donation import donation_status

	blocked = donation_status(donor)
	if blocked.get("blocked"):
		return blocked  # deferred or too soon: no screening to continue
	for s in frappe.get_all("Blood Donor Screening", filters={"donor": donor, "docstatus": ["<", 2]},
			fields=["name", "docstatus", "result"], order_by="creation desc", limit=5):
		if s.docstatus == 0:
			return {"open_screening": s.name}
		if s.result == "Accepted" and not frappe.db.exists("Blood Donation", {"donor_screening": s.name, "docstatus": ["<", 2]}) \
				and not frappe.db.exists("Blood Donor Test", {"donor_screening": s.name, "docstatus": 1, "overall_result": ["!=", "Non-Reactive"]}) \
				and not _screening_expired(s.name):
			return {"open_screening": s.name}
	return donation_status(donor)


def _screening_expired(name):
	from frappe.utils import add_to_date, cint, get_datetime, now_datetime
	from blood_bank.utils import setting
	when = frappe.db.get_value("Blood Donor Screening", name, "screening_datetime")
	hours = cint(setting("test_validity_hours")) or 72
	return not when or add_to_date(get_datetime(when), hours=hours) < now_datetime()
