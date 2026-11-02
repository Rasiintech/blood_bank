# Copyright (c) 2026, Cibaar Technologies and contributors
# Run: bench --site <test-site> run-tests --app blood_bank

import random

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, now_datetime

from blood_bank.blood_bank.doctype.blood_crossmatch.blood_crossmatch import get_compatible_units
from blood_bank.blood_bank.doctype.blood_unit.blood_unit import release_units
from blood_bank.utils import check_compatibility, parse_blood_group


def settings(**values):
	s = frappe.get_single("Blood Bank Settings")
	s.update(values)
	s.save()


def make_donor(name, sex="Male"):
	for g in ("Male", "Female"):
		if not frappe.db.exists("Gender", g):
			frappe.get_doc({"doctype": "Gender", "gender": g}).insert()
	patient = frappe.get_doc({"doctype": "Patient", "first_name": name, "sex": sex, "dob": "1990-01-01",
		"mobile": f"+25261{random.randint(1000000, 9999999)}"}).insert()
	return frappe.get_doc({"doctype": "Blood Donor", "patient": patient.name}).insert()


def make_screening(donor, **kw):
	sc = frappe.get_doc({"doctype": "Blood Donor Screening", "donor": donor.name, "donor_type": "Voluntary",
		"weight_kg": 70, "bp_systolic": 120, "bp_diastolic": 80, "pulse": 72, "temperature": 36.8, **kw}).insert()
	for q in sc.questionnaire:
		q.answer = "Yes" if "eaten" in q.question else "No"
	sc.save()
	return sc


def make_test(donor, sc, group="O Positive", reactive=None, donation=None):
	t = frappe.get_doc({"doctype": "Blood Donor Test", "donor": donor.name, "donor_screening": sc.name,
		"blood_group": group, "hb_g_dl": 14, "blood_donation": donation}).insert()
	for row in t.tests:
		row.result = "Reactive" if row.screening_test == reactive else "Non-Reactive"
	t.save()
	t.submit()
	return t


def make_patient(first):
	for g in ("Male", "Female"):
		if not frappe.db.exists("Gender", g):
			frappe.get_doc({"doctype": "Gender", "gender": g}).insert()
	return frappe.get_doc({"doctype": "Patient", "first_name": first, "last_name": "Test", "sex": "Female"}).insert()


class TestCompatibility(FrappeTestCase):
	def test_rules(self):
		self.assertTrue(check_compatibility("Red Cell", "A Positive", "O Negative")[0])
		self.assertFalse(check_compatibility("Red Cell", "O Positive", "A Positive")[0])
		self.assertFalse(check_compatibility("Red Cell", "A Negative", "A Positive")[0])
		self.assertTrue(check_compatibility("Plasma", "O Positive", "AB Negative")[0])
		self.assertFalse(check_compatibility("Plasma", "A Positive", "O Positive")[0])
		self.assertFalse(check_compatibility("Identical", "A Positive", "O Positive")[0])
		self.assertTrue(check_compatibility("Identical", "A Positive", "O Positive", emergency=True)[0])
		self.assertFalse(check_compatibility("Red Cell", None, "A Positive", emergency=True)[0])
		self.assertTrue(check_compatibility("Red Cell", None, "O Negative", emergency=True)[0])

	def test_parse_group(self):
		self.assertEqual(parse_blood_group("A+"), "A Positive")
		self.assertEqual(parse_blood_group("O Rh -ve"), "O Negative")
		self.assertIsNone(parse_blood_group("A"))


class TestDonorFromPatient(FrappeTestCase):
	def test_donor_reuses_patient(self):
		donor = make_donor("Reuse Patient", sex="Female")
		self.assertEqual(donor.sex, "Female")
		self.assertEqual(donor.age_years, frappe.utils.getdate().year - 1990 - (1 if (frappe.utils.getdate().month, frappe.utils.getdate().day) < (1, 1) else 0))
		self.assertTrue(donor.donor_name.startswith("Reuse Patient"))
		self.assertRaises(frappe.ValidationError, frappe.get_doc({"doctype": "Blood Donor", "patient": donor.patient}).insert)
		from blood_bank.blood_bank.doctype.blood_donor.blood_donor import get_or_create_donor
		self.assertEqual(get_or_create_donor(donor.patient), donor.name)


class TestScreening(FrappeTestCase):
	def test_questions_follow_sex_and_vitals_are_read(self):
		s = frappe.get_single("Blood Bank Settings")
		self.assertFalse(any("tattoo" in q.question.lower() for q in s.screening_questions))
		male = make_donor("Male Q", sex="Male")
		frappe.get_doc({"doctype": "Vital Signs", "patient": male.patient, "signs_date": frappe.utils.nowdate(),
			"signs_time": frappe.utils.nowtime(), "weight": 72, "bp": "118/76", "pulse": "70", "temperature": "36.6"}).insert()
		sc = frappe.get_doc({"doctype": "Blood Donor Screening", "donor": male.name, "donor_type": "Voluntary"}).insert()
		self.assertFalse(any("pregnant" in q.question.lower() for q in sc.questionnaire))
		self.assertEqual((sc.weight_kg, sc.bp_systolic, sc.bp_diastolic, sc.pulse), (72, 118, 76, 70))
		female = make_donor("Female Q", sex="Female")
		sc2 = frappe.get_doc({"doctype": "Blood Donor Screening", "donor": female.name, "donor_type": "Voluntary"}).insert()
		self.assertTrue(any("pregnant" in q.question.lower() for q in sc2.questionnaire))
		self.assertTrue(s.stock_levels)


class TestBloodBankFlow(FrappeTestCase):
	def setUp(self):
		settings(testing_mode="Test Donor First", require_invoice_before_issue=0, auto_release_cleared_units=0)

	def test_donor_to_transfusion(self):
		donor = make_donor("Flow Donor")
		sc = make_screening(donor)
		sc.submit()
		self.assertEqual(sc.result, "Accepted")
		t = make_test(donor, sc, "A Positive")
		don = frappe.get_doc({"doctype": "Blood Donation", "donor": donor.name, "donor_screening": sc.name,
			"donor_test": t.name, "bag_type": "Double", "volume_ml": 450}).insert()
		don.submit()
		unit = frappe.get_doc("Blood Unit", don.blood_unit)
		self.assertEqual((unit.status, unit.test_status), ("Quarantine", "Cleared"))
		self.assertEqual(release_units([unit.name])["released"], [unit.name])

		prep = frappe.get_doc({"doctype": "Blood Component Preparation", "source_unit": unit.name,
			"items": [{"component": "Red Cells (RBC)"}, {"component": "Fresh Frozen Plasma (FFP)"}]}).insert()
		prep.submit()
		rbc = f"{unit.name}-RBC"
		self.assertEqual(frappe.db.get_value("Blood Unit", rbc, "status"), "Available")
		self.assertEqual(frappe.db.get_value("Blood Unit", unit.name, "status"), "Processed")

		patient = make_patient("Flow")
		req = frappe.get_doc({"doctype": "Blood Request", "patient": patient.name, "external_practitioner": "Dr T",
			"indication": "Anaemia", "patient_blood_group": "A Positive",
			"items": [{"component": "Red Cells (RBC)", "units_required": 1}]}).insert()
		req.submit()
		self.assertIn(rbc, [u["blood_unit"] for u in get_compatible_units(req.name)])
		xm = frappe.get_doc({"doctype": "Blood Crossmatch", "blood_request": req.name, "patient_blood_group": "A Positive",
			"items": [{"blood_unit": rbc, "result": "Compatible"}]}).insert()
		xm.submit()
		self.assertEqual(frappe.db.get_value("Blood Unit", rbc, "status"), "Reserved")
		iss = frappe.get_doc({"doctype": "Blood Issue", "blood_request": req.name, "received_by": "Nurse",
			"items": [{"blood_unit": rbc}]}).insert()
		iss.submit()
		if not frappe.db.exists("User", "bb-checker@test.local"):
			frappe.get_doc({"doctype": "User", "email": "bb-checker@test.local", "first_name": "Checker", "send_welcome_email": 0}).insert()
		tr = frappe.get_doc({"doctype": "Blood Transfusion", "blood_issue": iss.name, "blood_unit": rbc,
			"first_checker": "Administrator", "second_checker": "bb-checker@test.local", "patient_identity_confirmed": 1,
			"unit_label_checked": 1, "unit_expiry_checked": 1, "start_datetime": add_to_date(now_datetime(), minutes=1),
			"end_datetime": add_to_date(now_datetime(), hours=2), "outcome": "Completed"}).insert()
		tr.submit()
		self.assertEqual(frappe.db.get_value("Blood Unit", rbc, "status"), "Transfused")
		self.assertEqual(frappe.db.get_value("Blood Request", req.name, "status"), "Completed")

	def test_reactive_bag_is_discarded(self):
		settings(testing_mode="Test the Bag")
		donor = make_donor("Bag Donor", sex="Female")
		sc = make_screening(donor)
		sc.submit()
		don = frappe.get_doc({"doctype": "Blood Donation", "donor": donor.name, "donor_screening": sc.name,
			"bag_type": "Single", "volume_ml": 450}).insert()
		don.submit()
		self.assertFalse(release_units([don.blood_unit])["released"])
		make_test(donor, sc, "B Positive", reactive="HIV", donation=don.name)
		self.assertEqual(frappe.db.get_value("Blood Unit", don.blood_unit, "status"), "Discarded")
		self.assertEqual(frappe.db.get_value("Blood Donor", donor.name, "status"), "Permanently Deferred")
		self.assertEqual(frappe.db.get_value("Patient", donor.patient, "blood_group"), "B Positive")

	def test_screening_defers_low_hb(self):
		donor = make_donor("Low Hb", sex="Female")
		sc = make_screening(donor, hb_g_dl=10.5)
		self.assertEqual((sc.result, sc.deferral_reason), ("Deferred", "Low Haemoglobin"))

	def test_issue_requires_crossmatch_and_emergency_needs_o(self):
		rec = frappe.get_doc({"doctype": "Blood Unit Receipt", "source_name": "NBS", "items": [
			{"external_unit_number": f"T-{random.randint(1, 10**6)}", "component": "Red Cells (RBC)", "blood_group": "A Positive",
			 "expiry_datetime": add_days(now_datetime(), 10)},
			{"external_unit_number": f"T-{random.randint(1, 10**6)}", "component": "Red Cells (RBC)", "blood_group": "O Negative",
			 "expiry_datetime": add_days(now_datetime(), 10)}]}).insert()
		rec.submit()
		a_pos, o_neg = rec.items[0].blood_unit, rec.items[1].blood_unit
		patient = make_patient("Emergency")
		req = frappe.get_doc({"doctype": "Blood Request", "patient": patient.name, "external_practitioner": "ER",
			"urgency": "Emergency", "indication": "Trauma", "items": [{"component": "Red Cells (RBC)", "units_required": 1}]}).insert()
		req.submit()
		issue = lambda unit, emergency: frappe.get_doc({"doctype": "Blood Issue", "blood_request": req.name,
			"received_by": "Nurse", "emergency_release": emergency, "authorised_by": "Administrator",
			"items": [{"blood_unit": unit}]}).insert()
		self.assertRaises(frappe.ValidationError, issue, o_neg, 0)
		self.assertRaises(frappe.ValidationError, issue, a_pos, 1)
		issue(o_neg, 1).submit()
		self.assertEqual(frappe.db.get_value("Blood Unit", o_neg, "status"), "Issued")
