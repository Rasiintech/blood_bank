# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

from blood_bank.utils import donor_age


class BloodDonor(Document):
	def validate(self):
		self.donor_name = " ".join((self.donor_name or "").split())
		if self.date_of_birth:
			if getdate(self.date_of_birth) > getdate(nowdate()):
				frappe.throw(_("Date of birth cannot be in the future"))
			self.age_years = donor_age(self)
		self.check_duplicate()

	def check_duplicate(self):
		for field, label in (("id_number", _("ID Number")), ("mobile_no", _("Mobile No"))):
			value = (self.get(field) or "").strip()
			if not value:
				continue
			other = frappe.db.get_value("Blood Donor", {field: value, "name": ["!=", self.name]}, ["name", "donor_name"], as_dict=True)
			if other:
				msg = _("{0} {1} is already registered to donor {2} ({3})").format(label, value, other.name, other.donor_name)
				if field == "id_number":
					frappe.throw(msg, title=_("Duplicate Donor"))
				frappe.msgprint(msg, indicator="orange", alert=True)


@frappe.whitelist()
def make_patient(donor):
	"""Create (or reuse) a Patient so the lab can record the donor's tests."""
	d = frappe.get_doc("Blood Donor", donor)
	d.check_permission("write")
	if d.patient:
		return d.patient
	if d.mobile_no:
		existing = frappe.db.get_value("Patient", {"mobile": d.mobile_no, "patient_name": d.donor_name}, "name")
		if existing:
			d.db_set("patient", existing)
			return existing
	parts = d.donor_name.split(" ", 1)
	p = frappe.new_doc("Patient")
	p.first_name = parts[0]
	if len(parts) > 1 and p.meta.has_field("last_name"):
		p.last_name = parts[1]
	p.sex = d.sex
	if d.date_of_birth:
		p.dob = d.date_of_birth
	if d.mobile_no and p.meta.has_field("mobile"):
		p.mobile = d.mobile_no
	if d.blood_group and p.meta.has_field("blood_group"):
		p.blood_group = d.blood_group
	p.flags.ignore_mandatory = True
	p.insert(ignore_permissions=True)
	d.db_set("patient", p.name)
	return p.name
