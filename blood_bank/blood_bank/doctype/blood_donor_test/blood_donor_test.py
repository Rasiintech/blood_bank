# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from blood_bank.lab import fill_donor_test
from blood_bank.utils import (clear_deferral_from, defer_donor, get_settings, min_hb, set_patient_blood_group,
	setting, update_unit)


class BloodDonorTest(Document):
	def before_insert(self):
		if not self.tests:
			self.load_tests()

	def onload(self):
		if self.is_new() and not self.tests:
			self.load_tests()

	def load_tests(self):
		for t in frappe.get_all("Blood Screening Test", filters={"disabled": 0}, fields=["name", "mandatory"], order_by="mandatory desc, name asc"):
			self.append("tests", {"screening_test": t.name, "result": "Pending", "mandatory": t.mandatory})
		if not self.lab_doctype:
			self.lab_doctype = get_settings().lab_doctype

	@frappe.whitelist()
	def prepare(self):
		"""Called when the form opens: load the test list and find the donor's Lab Result."""
		if not self.tests:
			self.load_tests()
		if not self.lab_doctype:
			self.lab_doctype = get_settings().lab_doctype
		patients = self.lab_patients()
		if self.lab_doctype and not self.lab_reference and patients:
			meta = frappe.get_meta(self.lab_doctype)
			if meta.has_field("patient"):
				rows = frappe.get_all(self.lab_doctype, filters={"patient": ["in", patients], "docstatus": ["<", 2]},
					fields=["name", "docstatus"], order_by="creation desc", limit=1)
				if rows:
					self.lab_reference = rows[0].name
					if rows[0].docstatus == 1:
						try:
							fill_donor_test(self)
						except Exception:
							pass
		self.evaluate()
		return {"patients": patients}

	def lab_patients(self):
		"""The donor's own Patient, plus the patient a replacement donor gives for."""
		patients = []
		if self.donor:
			p = frappe.db.get_value("Blood Donor", self.donor, "patient")
			if p:
				patients.append(p)
		if self.donor_screening:
			p = frappe.db.get_value("Blood Donor Screening", self.donor_screening, "replacement_for")
			if p:
				patients.append(p)
		return patients

	def validate(self):
		scr = frappe.db.get_value("Blood Donor Screening", self.donor_screening, ["donor", "docstatus", "result"], as_dict=True)
		if not scr or scr.donor != self.donor:
			frappe.throw(_("Donor Screening {0} belongs to another donor").format(self.donor_screening))
		if scr.docstatus != 1 or scr.result != "Accepted":
			frappe.throw(_("Donor Screening {0} must be submitted and Accepted before testing").format(self.donor_screening))
		if self.blood_donation:
			don = frappe.db.get_value("Blood Donation", self.blood_donation, ["donor", "docstatus"], as_dict=True)
			if not don or don.donor != self.donor or don.docstatus != 1:
				frappe.throw(_("Blood Donation {0} is not a submitted donation of this donor").format(self.blood_donation))
		if self.verified_by and self.verified_by == self.tested_by:
			frappe.throw(_("Verified By must be a different person from Tested By"))
		self.evaluate()

	def evaluate(self):
		sex = frappe.db.get_value("Blood Donor", self.donor, "sex")
		self.hb_ok = 1 if (not self.hb_g_dl or flt(self.hb_g_dl) >= min_hb(sex)) else 0
		results = [t.result for t in self.tests]
		if "Reactive" in results:
			self.overall_result = "Reactive"
		elif any(t.result == "Pending" and t.mandatory for t in self.tests):
			self.overall_result = "Incomplete"
		else:
			self.overall_result = "Non-Reactive"

	@frappe.whitelist()
	def fetch_from_lab(self):
		if not (self.lab_doctype and self.lab_reference):
			frappe.throw(_("Select the lab document first"))
		summary = fill_donor_test(self)
		self.evaluate()
		return summary

	def before_submit(self):
		if self.overall_result == "Incomplete":
			frappe.throw(_("Some mandatory tests are still Pending"))
		if not self.blood_group:
			frappe.throw(_("Blood group is required"))

	def on_submit(self):
		donor = frappe.get_doc("Blood Donor", self.donor)
		if donor.blood_group and donor.blood_group != self.blood_group:
			frappe.throw(_("Donor {0} is recorded as {1} but this test says {2}. Re-group before continuing.")
				.format(donor.name, donor.blood_group, self.blood_group), title=_("Blood Group Mismatch"))
		if not donor.blood_group:
			frappe.db.set_value("Blood Donor", self.donor, "blood_group", self.blood_group)
		set_patient_blood_group(donor.patient, self.blood_group)

		if self.overall_result == "Reactive":
			reactive = [t.screening_test for t in self.tests if t.result == "Reactive"]
			reason = frappe.db.get_value("Blood Screening Test", reactive[0], "deferral_reason") or "Reactive Screening Test"
			defer_donor(self.donor, reason, self, notes=_("Reactive: {0} ({1})").format(", ".join(reactive), self.name))
			frappe.msgprint(_("Donor deferred. Counsel the donor confidentially and refer for confirmatory testing."),
				title=_("Reactive Result"), indicator="red")
		elif not self.hb_ok and not self.blood_donation:
			defer_donor(self.donor, "Low Haemoglobin", self, notes=_("Hb {0} g/dL ({1})").format(self.hb_g_dl, self.name))

		if self.blood_donation:
			frappe.db.set_value("Blood Donation", self.blood_donation, "blood_group", self.blood_group)
			self.apply_to_units()

	def apply_to_units(self):
		"""Test the Bag mode: clear or discard every unit made from the donation."""
		units = frappe.get_all("Blood Unit", filters={"blood_donation": self.blood_donation,
			"status": ["not in", ["Discarded", "Transfused"]]}, fields=["name", "status"])
		if self.overall_result == "Reactive":
			from blood_bank.blood_bank.doctype.blood_unit_discard.blood_unit_discard import discard_units
			discard_units([u.name for u in units if u.status != "Processed"], "Reactive Test", self)
			for u in units:
				if u.status == "Processed":
					update_unit(u.name, test_status="Reactive")
		else:
			auto = frappe.utils.cint(setting("auto_release_cleared_units"))
			for u in units:
				values = {"test_status": "Cleared", "donor_test": self.name, "blood_group": self.blood_group}
				if auto and u.status == "Quarantine":
					values.update(status="Available", released_by=frappe.session.user, released_on=frappe.utils.now_datetime())
				update_unit(u.name, **values)

	def on_cancel(self):
		if frappe.db.exists("Blood Donation", {"donor_test": self.name, "docstatus": 1}):
			frappe.throw(_("A submitted Blood Donation uses this test; cancel it first"))
		if self.blood_donation:
			for u in frappe.get_all("Blood Unit", filters={"blood_donation": self.blood_donation, "donor_test": self.name},
					fields=["name", "status"]):
				if u.status not in ("Quarantine", "Available"):
					frappe.throw(_("Unit {0} is already {1}; this test cannot be cancelled").format(u.name, u.status))
				update_unit(u.name, status="Quarantine", test_status="Pending", donor_test=None)
		clear_deferral_from(self)
