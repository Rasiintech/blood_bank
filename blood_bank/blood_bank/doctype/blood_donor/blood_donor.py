# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from blood_bank.utils import donor_age, get_patient_blood_group, set_patient_blood_group


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
