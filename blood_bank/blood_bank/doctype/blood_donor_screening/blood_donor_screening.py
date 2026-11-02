# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate

from blood_bank.utils import (clear_deferral_from, defer_donor, donation_interval_days, donor_age,
	get_settings, min_hb, setting)


class BloodDonorScreening(Document):
	def onload(self):
		if self.is_new() and not self.questionnaire:
			self.load_questions()

	def before_insert(self):
		if not self.questionnaire:
			self.load_questions()

	def load_questions(self):
		for q in get_settings().screening_questions:
			self.append("questionnaire", {"question": q.question, "defer_if_answer": q.defer_if_answer,
				"deferral_reason": q.deferral_reason})

	def validate(self):
		donor = frappe.get_doc("Blood Donor", self.donor)
		if not self.donor_type:
			self.donor_type = donor.default_donor_type or "Voluntary"
		if self.donor_type == "Replacement" and not (self.replacement_for or self.blood_request):
			frappe.throw(_("Select the patient (or Blood Request) this replacement donor is donating for"))
		if self.blood_request and not self.replacement_for:
			self.replacement_for = frappe.db.get_value("Blood Request", self.blood_request, "patient")
		self.evaluate(donor)

	def evaluate(self, donor):
		"""Fill result, reason and notes from the rules in Blood Bank Settings."""
		problems = []  # (message, deferral reason)
		if donor.status == "Permanently Deferred":
			problems.append((_("Donor is permanently deferred ({0})").format(donor.deferral_reason or ""), donor.deferral_reason or "Reactive Screening Test"))
		elif donor.status == "Temporarily Deferred" and donor.deferred_until and getdate(donor.deferred_until) >= getdate(self.screening_datetime):
			problems.append((_("Donor is deferred until {0}").format(frappe.format(donor.deferred_until, "Date")), donor.deferral_reason or "Questionnaire Answer"))

		age = donor_age(donor)
		if age is not None and not (cint(setting("min_donor_age")) <= age <= cint(setting("max_donor_age"))):
			problems.append((_("Age {0} is outside {1}-{2}").format(age, setting("min_donor_age"), setting("max_donor_age")), "Age Out of Range"))

		if donor.last_donation_date:
			next_ok = add_days(donor.last_donation_date, donation_interval_days(donor.sex))
			if getdate(self.screening_datetime) < getdate(next_ok):
				problems.append((_("Last donation was {0}; next allowed {1}").format(
					frappe.format(donor.last_donation_date, "Date"), frappe.format(next_ok, "Date")), "Donated Too Recently"))

		if self.weight_kg and flt(self.weight_kg) < flt(setting("min_weight_kg")):
			problems.append((_("Weight {0} kg is below {1} kg").format(self.weight_kg, setting("min_weight_kg")), "Underweight"))
		if self.hb_g_dl and flt(self.hb_g_dl) < min_hb(donor.sex):
			problems.append((_("Hb {0} g/dL is below {1}").format(self.hb_g_dl, min_hb(donor.sex)), "Low Haemoglobin"))
		if self.bp_systolic and not (cint(setting("min_systolic")) <= cint(self.bp_systolic) <= cint(setting("max_systolic"))):
			problems.append((_("Systolic BP {0} out of range").format(self.bp_systolic), "Blood Pressure Out of Range"))
		if self.bp_diastolic and not (cint(setting("min_diastolic")) <= cint(self.bp_diastolic) <= cint(setting("max_diastolic"))):
			problems.append((_("Diastolic BP {0} out of range").format(self.bp_diastolic), "Blood Pressure Out of Range"))
		if self.pulse and not (cint(setting("min_pulse")) <= cint(self.pulse) <= cint(setting("max_pulse"))):
			problems.append((_("Pulse {0} out of range").format(self.pulse), "Pulse Out of Range"))
		if self.temperature and flt(self.temperature) > flt(setting("max_temperature")):
			problems.append((_("Temperature {0} °C is too high").format(self.temperature), "Fever / Recent Illness"))

		for q in self.questionnaire:
			if q.answer and q.answer == q.defer_if_answer:
				problems.append((_("Answered {0}: {1}").format(q.answer, q.question), q.deferral_reason or "Questionnaire Answer"))

		if problems:
			self.result = "Deferred"
			self.eligibility_notes = "\n".join(p[0] for p in problems)
			# Use the longest deferral among the problems
			self.deferral_reason = self.pick_reason([p[1] for p in problems])
			self.deferred_until = self.until_for(self.deferral_reason, donor)
		else:
			self.result = "Accepted"
			self.eligibility_notes = _("All checks passed")
			self.deferral_reason = None
			self.deferred_until = None

	def pick_reason(self, reasons):
		best, best_days = None, -1
		for r in reasons:
			if not r or not frappe.db.exists("Blood Deferral Reason", r):
				continue
			dtype, days = frappe.db.get_value("Blood Deferral Reason", r, ["deferral_type", "default_days"])
			score = 10**6 if dtype == "Permanent" else cint(days)
			if score > best_days:
				best, best_days = r, score
		return best

	def until_for(self, reason, donor):
		if not reason:
			return None
		dtype, days = frappe.db.get_value("Blood Deferral Reason", reason, ["deferral_type", "default_days"])
		if dtype == "Permanent":
			return None
		if reason == "Donated Too Recently" and donor.last_donation_date:
			return add_days(donor.last_donation_date, donation_interval_days(donor.sex))
		return add_days(getdate(self.screening_datetime), cint(days))

	def before_submit(self):
		if any(q.answer in (None, "") for q in self.questionnaire):
			frappe.throw(_("Answer every screening question before submitting"))

	def on_submit(self):
		if self.result == "Deferred" and self.deferral_reason:
			defer_donor(self.donor, self.deferral_reason, self, until=self.deferred_until, notes=self.eligibility_notes)

	def on_cancel(self):
		clear_deferral_from(self)
