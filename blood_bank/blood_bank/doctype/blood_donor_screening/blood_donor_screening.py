# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_to_date, cint, flt, get_datetime, getdate, now_datetime

from blood_bank.utils import (clear_deferral_from, defer_donor, donation_interval_days, donor_age,
	get_settings, min_hb, setting)


class BloodDonorScreening(Document):
	def before_insert(self):
		if not self.questionnaire:
			self.load_questions()
		if not self.vital_signs:
			self.fetch_vital_signs(quiet=True)

	@frappe.whitelist()
	def load_for_donor(self):
		"""Called when the donor is picked: questions for the donor's sex + latest vital signs."""
		self.set("questionnaire", [])
		self.load_questions()
		self.fetch_vital_signs(quiet=True)

	def load_questions(self):
		sex = frappe.db.get_value("Blood Donor", self.donor, "sex") if self.donor else None
		for q in get_settings().screening_questions:
			applies = q.get("applies_to") or "All"
			if applies != "All" and sex and applies != sex:
				continue
			self.append("questionnaire", {"question": q.question, "defer_if_answer": q.defer_if_answer,
				"deferral_reason": q.deferral_reason})

	@frappe.whitelist()
	def fetch_vital_signs(self, quiet=False):
		"""Copy weight, BP, pulse and temperature from the donor's latest Vital Signs."""
		patient = frappe.db.get_value("Blood Donor", self.donor, "patient") if self.donor else None
		if not patient:
			return None
		hours = cint(setting("vital_signs_max_age_hours")) or 24
		rows = frappe.get_all("Vital Signs", filters={"patient": patient, "docstatus": ["<", 2]},
			fields=["name", "signs_date", "signs_time", "weight", "bp_systolic", "bp_diastolic", "bp", "pulse", "temperature"],
			order_by="signs_date desc, signs_time desc, creation desc", limit=1)
		if not rows:
			if not quiet:
				frappe.msgprint(_("No Vital Signs found for this donor. Record them in Vital Signs or type them here."))
			return None
		v = rows[0]
		taken = get_datetime(f"{v.signs_date} {v.signs_time or '00:00:00'}")
		if taken < add_to_date(now_datetime(), hours=-hours):
			if not quiet:
				frappe.msgprint(_("Latest Vital Signs ({0}) are older than {1} hours. Record new ones.").format(v.name, hours))
			return None
		sys_bp, dia_bp = v.bp_systolic, v.bp_diastolic
		if (not sys_bp or not dia_bp) and v.bp and "/" in str(v.bp):
			sys_bp, dia_bp = str(v.bp).split("/", 1)
		self.vital_signs = v.name
		if v.weight:
			self.weight_kg = flt(v.weight)
		for field, value in (("bp_systolic", sys_bp), ("bp_diastolic", dia_bp), ("pulse", v.pulse)):
			n = _number(value)
			if n:
				self.set(field, int(n))
		t = _number(v.temperature)
		if t:
			self.temperature = t
		return v.name

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
		missing = [self.meta.get_label(f) for f in ("weight_kg", "bp_systolic", "bp_diastolic", "pulse", "temperature")
			if not flt(self.get(f))]
		if missing:
			frappe.throw(_("Enter the vital signs before submitting: {0}").format(", ".join(missing)), title=_("Vitals Missing"))

	@frappe.whitelist()
	def order_screening_tests(self):
		"""Order the donor's lab tests: a Sample Collection directly when free, a Sales Invoice when charged."""
		if self.docstatus != 1 or self.result != "Accepted":
			frappe.throw(_("Only an accepted, submitted screening can order tests"))
		for dt, field in (("Sample Collection", "sample_collection"), ("Sales Invoice", "sales_invoice")):
			name = self.get(field)
			if name and frappe.db.exists(dt, name) and frappe.db.get_value(dt, name, "docstatus") != 2:
				return frappe.get_doc(dt, name)
		templates = [r.lab_test_template for r in get_settings().donor_lab_tests]
		if not templates:
			frappe.throw(_("Add the Lab Tests to Order in Blood Bank Settings first"))
		patient = frappe.db.get_value("Blood Donor", self.donor, "patient")
		charge = cint(setting("charge_replacement_donors" if self.donor_type == "Replacement" else "charge_voluntary_donors"))
		doc = make_screening_invoice(self, patient, templates) if charge else make_sample_collection(self, patient, templates)
		return doc

	def on_submit(self):
		if self.result == "Deferred" and self.deferral_reason:
			defer_donor(self.donor, self.deferral_reason, self, until=self.deferred_until, notes=self.eligibility_notes)

	def on_cancel(self):
		clear_deferral_from(self)


def _number(value):
	m = re.search(r"\d+(\.\d+)?", str(value or ""))
	return flt(m.group(0)) if m else None


@frappe.whitelist()
def get_limits(donor=None):
	"""Acceptance ranges shown under the vital-sign fields."""
	sex = frappe.db.get_value("Blood Donor", donor, "sex") if donor else None
	return {
		"weight": flt(setting("min_weight_kg")),
		"hb": min_hb(sex) if sex else None,
		"systolic": [cint(setting("min_systolic")), cint(setting("max_systolic"))],
		"diastolic": [cint(setting("min_diastolic")), cint(setting("max_diastolic"))],
		"pulse": [cint(setting("min_pulse")), cint(setting("max_pulse"))],
		"temperature": flt(setting("max_temperature")),
	}


def _lab_test_table(meta):
	"""The child table of a doctype whose rows link to Lab Test Template, and that link's fieldname."""
	for tdf in meta.get_table_fields():
		for df in frappe.get_meta(tdf.options).fields:
			if df.fieldtype == "Link" and df.options == "Lab Test Template":
				return tdf.fieldname, df.fieldname
	return None, None


def make_sample_collection(screening, patient, templates):
	"""Free screening: straight to Sample Collection (like Hajj Screening), tagged with the screening."""
	meta = frappe.get_meta("Sample Collection")
	table, link = _lab_test_table(meta)
	sc = frappe.new_doc("Sample Collection")
	sc.patient = patient
	if meta.has_field("company") and not sc.get("company"):
		sc.company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
	if meta.has_field("blood_donor_screening"):
		sc.blood_donor_screening = screening.name
	if meta.has_field("sample_qty") and not sc.get("sample_qty"):
		sc.sample_qty = 1
	if meta.has_field("sample") and not sc.get("sample"):
		sample = next((frappe.db.get_value("Lab Test Template", t, "sample") for t in templates
			if frappe.db.get_value("Lab Test Template", t, "sample")), None)
		if not sample and frappe.db.exists("DocType", "Lab Test Sample"):
			sample = frappe.db.get_value("Lab Test Sample", {"sample": "Blood"}) or frappe.db.get_value("Lab Test Sample", {})
			if not sample:
				sample = frappe.get_doc({"doctype": "Lab Test Sample", "sample": "Blood"}).insert(ignore_permissions=True).name
		sc.sample = sample
	if table:
		for t in templates:
			sc.append(table, {link: t})
	elif meta.has_field("template"):
		sc.template = templates[0]
	sc.insert()
	screening.db_set("sample_collection", sc.name)
	return sc


def make_screening_invoice(screening, patient, templates):
	"""Charged screening: a Sales Invoice with each template's item; the normal lab flow follows."""
	draft = frappe.db.get_value("Sales Invoice", {"blood_donor_screening": screening.name, "docstatus": 0})
	if draft:
		return frappe.get_doc("Sales Invoice", draft)
	customer = frappe.db.get_value("Patient", patient, "customer")
	if not customer:
		frappe.throw(_("Patient {0} has no Customer. Open the Patient and create the Customer first.").format(patient))
	si = frappe.new_doc("Sales Invoice")
	si.customer = customer
	if si.meta.has_field("patient"):
		si.patient = patient
	si.blood_donor_screening = screening.name
	for t in templates:
		item = frappe.db.get_value("Lab Test Template", t, "item") or t
		si.append("items", {"item_code": item, "qty": 1})
	si.set_missing_values()
	si.calculate_taxes_and_totals()
	return si
