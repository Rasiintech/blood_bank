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
		settings(testing_mode="Test Donor First", require_invoice_before_issue=0, auto_release_cleared_units=0,
			outpatient_billing="On Issue", inpatient_billing="On Issue", non_replacement_fee="Off")

	def test_manual_values_and_duplicate_donation(self):
		from blood_bank.blood_bank.doctype.blood_donation.blood_donation import donation_status
		donor = make_donor("Manual Donor")
		sc = make_screening(donor)
		sc.submit()
		t = frappe.get_doc({"doctype": "Blood Donor Test", "donor": donor.name, "donor_screening": sc.name,
			"blood_group": "O Positive", "hb_g_dl": 14}).insert()
		for row in t.tests:
			row.lab_value = "Negative"
		t.save()
		self.assertEqual(t.overall_result, "Non-Reactive")
		t.submit()
		self.assertEqual(donation_status(donor.name, sc.name, t.name), {})
		don = frappe.get_doc({"doctype": "Blood Donation", "donor": donor.name, "donor_screening": sc.name,
			"donor_test": t.name, "bag_type": "Triple", "volume_ml": 450}).insert()
		don.submit()
		self.assertEqual(donation_status(donor.name, sc.name, t.name)["existing"], don.name)
		self.assertIn("blocked", donation_status(donor.name))
		from blood_bank.blood_bank.doctype.blood_donor.blood_donor import next_action
		self.assertIn("blocked", next_action(donor.name))
		unit = frappe.get_doc("Blood Unit", don.blood_unit)
		release_units([unit.name])
		from blood_bank.blood_bank.doctype.blood_component_preparation.blood_component_preparation import get_split_plan
		plan = get_split_plan(unit.name)
		self.assertEqual((plan["bag_type"], plan["max_components"]), ("Triple", 3))
		self.assertEqual([r["abbr"] for r in plan["rows"]], ["RBC", "FFP", "PLT"])
		self.assertEqual(sum(r["volume_ml"] for r in plan["rows"]), 450)
		prep = frappe.get_doc({"doctype": "Blood Component Preparation", "source_unit": unit.name,
			"items": [{"component": "Red Cells (RBC)"}, {"component": "Fresh Frozen Plasma (FFP)"}]}).insert()
		prep.submit()
		self.assertEqual(frappe.db.get_value("Blood Component Preparation", prep.name, "source_status"), "Processed")

	def test_cancel_test_order(self):
		donor = make_donor("Order Donor")
		sc = make_screening(donor)
		sc.submit()
		if not frappe.db.exists("Lab Test Sample", "Blood Test BB"):
			frappe.get_doc({"doctype": "Lab Test Sample", "sample": "Blood Test BB"}).insert()
		doc = frappe.get_doc({"doctype": "Sample Collection", "patient": donor.patient, "sample": "Blood Test BB", "sample_qty": 1,
			"company": frappe.get_all("Company", pluck="name", limit=1)[0], "blood_donor_screening": sc.name}).insert()
		sc.db_set("sample_collection", doc.name)
		sc.reload()
		self.assertEqual(sc.sync_donor_test()["donor_test"], None)
		self.assertIn("deleted", sc.cancel_test_order()[0])
		sc.reload()
		self.assertFalse(sc.sample_collection)
		self.assertFalse(frappe.db.exists("Sample Collection", doc.name))

	def test_suggested_donors_and_lab_values(self):
		from blood_bank.blood_bank.doctype.blood_request.blood_request import suggested_donors
		self.assertEqual(suggested_donors([{"component": "Whole Blood", "units_required": 2}]), 2)
		self.assertEqual(suggested_donors([{"component": "Red Cells (RBC)", "units_required": 2},
			{"component": "Fresh Frozen Plasma (FFP)", "units_required": 2}]), 2)
		self.assertEqual(suggested_donors([{"component": "Whole Blood", "units_required": 1},
			{"component": "Red Cells (RBC)", "units_required": 1}]), 2)
		from blood_bank.lab import latest_patient_values
		self.assertIsNone(latest_patient_values(make_patient("NoLab").name)["hb"])

	# ------------------------------------------------------------------ billing
	def billing_setup(self, **values):
		from blood_bank.install import create_billing_items
		create_billing_items()
		for code, rate in (("BB-RBC", 25), ("BB-XM", 5), ("BB-GRP", 3), ("BB-NRF", 10), ("BB-FFP", 20)):
			if not frappe.db.exists("Item Price", {"item_code": code, "price_list": "Standard Selling"}):
				frappe.get_doc({"doctype": "Item Price", "item_code": code, "price_list": "Standard Selling", "price_list_rate": rate}).insert()
		frappe.db.set_value("Blood Component", "Red Cells (RBC)", "billing_item", "BB-RBC")
		frappe.db.set_value("Blood Component", "Fresh Frozen Plasma (FFP)", "billing_item", "BB-FFP")
		settings(**dict({"crossmatch_charge": "Separate per crossmatch", "charge_blood_grouping": 1, "submit_charge_invoices": 1,
			"non_replacement_fee": "Off", "require_invoice_before_issue": 1}, **values))

	def stock(self, group, n, component="Red Cells (RBC)"):
		rec = frappe.get_doc({"doctype": "Blood Unit Receipt", "source_name": "NBS", "items": [
			{"external_unit_number": f"T-{random.randint(1, 10**8)}", "component": component, "blood_group": group,
			 "expiry_datetime": add_days(now_datetime(), 10)} for _ in range(n)]}).insert()
		rec.submit()
		return [r.blood_unit for r in rec.items]

	def billed_patient(self, first):
		p = make_patient(first)
		if not frappe.db.get_value("Patient", p.name, "customer"):
			c = frappe.get_doc({"doctype": "Customer", "customer_name": p.patient_name,
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}) or "All Customer Groups",
				"territory": frappe.db.get_value("Territory", {"is_group": 0}) or "All Territories"}).insert()
			frappe.db.set_value("Patient", p.name, "customer", c.name)
		return p

	def request(self, patient, group, units=2, **kw):
		req = frappe.get_doc(dict({"doctype": "Blood Request", "patient": patient.name, "external_practitioner": "Dr B",
			"indication": "Surgery", "patient_blood_group": group,
			"items": [{"component": "Red Cells (RBC)", "units_required": units}]}, **kw)).insert()
		req.submit()
		return frappe.get_doc("Blood Request", req.name)

	def totals(self, req):
		from blood_bank.billing import charged_so_far
		req.reload()
		return {k[0]: v for k, v in charged_so_far(req).items() if v}, req.total_charged

	def test_bill_on_issue(self):
		"""Charges follow what happened: grouping + each crossmatch, each bag issued; a returned bag is credited."""
		if not frappe.db.get_value("Company", {}, "name"):
			return
		self.billing_setup(outpatient_billing="On Issue")
		units = self.stock("A Positive", 2)
		req = self.request(self.billed_patient("OnIssue"), "A Positive")
		self.assertEqual(req.billing_mode, "On Issue")
		self.assertEqual(self.totals(req)[0], {})
		xm = frappe.get_doc({"doctype": "Blood Crossmatch", "blood_request": req.name, "patient_blood_group": "A Positive",
			"items": [{"blood_unit": u, "result": "Compatible"} for u in units]}).insert()
		xm.submit()
		self.assertEqual(self.totals(req), ({"Blood Grouping": 1, "Crossmatch": 2}, 13))
		iss = frappe.get_doc({"doctype": "Blood Issue", "blood_request": req.name, "received_by": "Nurse",
			"items": [{"blood_unit": u} for u in units]}).insert()
		iss.submit()
		self.assertEqual(self.totals(req), ({"Blood Grouping": 1, "Crossmatch": 2, "Blood Unit": 2}, 63))
		ret = frappe.get_doc({"doctype": "Blood Unit Return", "blood_issue": iss.name, "return_datetime": now_datetime(),
			"items": [{"blood_unit": units[1], "seal_intact": 1}]}).insert()
		ret.submit()
		self.assertEqual(self.totals(req), ({"Blood Grouping": 1, "Crossmatch": 2, "Blood Unit": 1}, 38))
		from blood_bank.billing import reconcile
		self.assertEqual(reconcile(frappe.get_doc("Blood Request", req.name)), {"charged": [], "credited": [], "problems": []})
		returns = [c.sales_invoice for c in frappe.get_doc("Blood Request", req.name).charges if c.qty < 0]
		self.assertTrue(returns and frappe.db.get_value("Sales Invoice", returns[0], "is_return"))

	def test_bill_on_request(self):
		"""Requested bags and crossmatches invoiced up front; issue needs the invoice; closing credits what was not used."""
		if not frappe.db.get_value("Company", {}, "name"):
			return
		self.billing_setup(outpatient_billing="On Request")
		units = self.stock("O Positive", 2)
		req = self.request(self.billed_patient("OnRequest"), "O Positive")
		self.assertEqual(req.billing_mode, "On Request")
		self.assertEqual(self.totals(req), ({"Blood Unit": 2, "Crossmatch": 2, "Blood Grouping": 1}, 63))
		xm = frappe.get_doc({"doctype": "Blood Crossmatch", "blood_request": req.name, "patient_blood_group": "O Positive",
			"items": [{"blood_unit": u, "result": "Compatible"} for u in units]}).insert()
		xm.submit()
		self.assertEqual(self.totals(req)[1], 63)
		iss = frappe.get_doc({"doctype": "Blood Issue", "blood_request": req.name, "received_by": "Nurse",
			"items": [{"blood_unit": units[0]}]}).insert()
		iss.submit()
		from blood_bank.billing import close_request
		close_request(req.name, "Surgery done, second bag not needed")
		self.assertEqual(self.totals(req), ({"Blood Unit": 1, "Crossmatch": 2, "Blood Grouping": 1}, 38))
		self.assertEqual(frappe.db.get_value("Blood Unit", units[1], "status"), "Available")

	def test_non_replacement_fee(self):
		if not frappe.db.get_value("Company", {}, "name"):
			return
		self.billing_setup(outpatient_billing="On Issue", non_replacement_fee="Per missing donor", non_replacement_grace_days=0,
			charge_blood_grouping=0)
		req = self.request(self.billed_patient("NoFamily"), "B Positive", units=1, replacement_donors_needed=2)
		from blood_bank.billing import close_request, waive_non_replacement_fee
		close_request(req.name, "Not needed")
		self.assertEqual(self.totals(req), ({"Non-Replacement Fee": 2}, 20))
		waive_non_replacement_fee(req.name, "Family cannot donate")
		self.assertEqual(self.totals(req), ({}, 0))
		settings(non_replacement_fee="Off")

	def test_plasma_needs_no_crossmatch(self):
		if not frappe.db.get_value("Company", {}, "name"):
			return
		self.billing_setup(outpatient_billing="On Issue")
		ffp = self.stock("AB Positive", 1, "Fresh Frozen Plasma (FFP)")[0]
		p = self.billed_patient("Plasma")
		req = frappe.get_doc({"doctype": "Blood Request", "patient": p.name, "external_practitioner": "Dr P", "indication": "DIC",
			"patient_blood_group": "A Positive", "items": [{"component": "Fresh Frozen Plasma (FFP)", "units_required": 1}]}).insert()
		req.submit()
		from blood_bank.blood_bank.doctype.blood_issue.blood_issue import get_reserved_units
		offered = get_reserved_units(req.name)  # plasma comes straight from stock: earliest expiry, compatible group
		self.assertEqual([u["component"] for u in offered], ["Fresh Frozen Plasma (FFP)"])
		self.assertTrue(ffp)
		frappe.get_doc({"doctype": "Blood Issue", "blood_request": req.name, "received_by": "Nurse",
			"items": [{"blood_unit": offered[0]["blood_unit"]}]}).insert().submit()
		self.assertEqual(self.totals(req)[0], {"Blood Grouping": 1, "Blood Unit": 1})

	def test_directed_donation(self):
		from blood_bank.blood_bank.doctype.blood_unit.blood_unit import release_directed
		patient = make_patient("Directed")
		req = frappe.get_doc({"doctype": "Blood Request", "patient": patient.name, "external_practitioner": "Dr D",
			"indication": "Surgery", "patient_blood_group": "A Positive",
			"items": [{"component": "Red Cells (RBC)", "units_required": 1}]}).insert()
		req.submit()
		def give(name, group):
			donor = make_donor(name)
			sc = make_screening(donor, donor_type="Directed", blood_request=req.name)
			sc.submit()
			t = make_test(donor, sc, group)
			d = frappe.get_doc({"doctype": "Blood Donation", "donor": donor.name, "donor_screening": sc.name,
				"donor_test": t.name, "bag_type": "Single", "volume_ml": 450}).insert()
			d.submit()
			return frappe.get_doc("Blood Unit", d.blood_unit)
		b_pos = give("Dir B", "B Positive")
		self.assertFalse(b_pos.directed_request)  # B+ cannot go to an A+ patient: general stock
		o_pos = give("Dir O", "O Positive")
		self.assertEqual(o_pos.directed_request, req.name)
		release_units([o_pos.name])
		other = frappe.get_doc({"doctype": "Blood Request", "patient": make_patient("Other").name, "external_practitioner": "Dr X",
			"indication": "Anaemia", "patient_blood_group": "O Positive",
			"items": [{"component": "Whole Blood", "units_required": 1}]}).insert()
		other.submit()
		self.assertNotIn(o_pos.name, [u["blood_unit"] for u in get_compatible_units(other.name)["units"]])
		self.assertEqual(frappe.db.get_value("Blood Request", req.name, "replacement_donations"), 2)
		release_directed(o_pos.name, "Patient discharged")
		self.assertIn(o_pos.name, [u["blood_unit"] for u in get_compatible_units(other.name)["units"]])

	def test_times_must_follow_each_other(self):
		patient = make_patient("Times")
		req = frappe.get_doc({"doctype": "Blood Request", "patient": patient.name, "external_practitioner": "Dr T",
			"indication": "Anaemia", "patient_blood_group": "A Positive",
			"items": [{"component": "Red Cells (RBC)", "units_required": 1}]}).insert()
		req.submit()
		unit = self.stock("A Positive", 1)[0]
		xm = frappe.get_doc({"doctype": "Blood Crossmatch", "blood_request": req.name, "patient_blood_group": "A Positive",
			"crossmatch_datetime": add_to_date(now_datetime(), hours=-3), "items": [{"blood_unit": unit, "result": "Compatible"}]})
		self.assertRaises(frappe.ValidationError, xm.insert)

	def test_bag_type_correction(self):
		from blood_bank.blood_bank.doctype.blood_donation.blood_donation import correct_bag_type
		donor = make_donor("Bag Donor")
		sc = make_screening(donor)
		sc.submit()
		t = make_test(donor, sc, "B Positive")
		don = frappe.get_doc({"doctype": "Blood Donation", "donor": donor.name, "donor_screening": sc.name,
			"donor_test": t.name, "bag_type": "Single", "volume_ml": 450}).insert()
		don.submit()
		release_units([don.blood_unit])
		rows = [{"component": "Red Cells (RBC)"}, {"component": "Fresh Frozen Plasma (FFP)"}, {"component": "Platelets (PLT)"}]
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Blood Component Preparation", "source_unit": don.blood_unit, "items": rows}).insert()
		self.assertEqual(correct_bag_type(don.name, "Triple", "Wrong entry"), "Triple")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Blood Component Preparation", "source_unit": don.blood_unit,
				"items": [{"component": "Fresh Frozen Plasma (FFP)"}, {"component": "Plasma"}]}).insert()
		prep = frappe.get_doc({"doctype": "Blood Component Preparation", "source_unit": don.blood_unit, "items": rows}).insert()
		prep.submit()
		with self.assertRaises(frappe.ValidationError):
			correct_bag_type(don.name, "Quadruple", "late")

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
		self.assertIn(rbc, [u["blood_unit"] for u in get_compatible_units(req.name)["units"]])
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
			"end_datetime": add_to_date(now_datetime(), minutes=5), "outcome": "Completed"}).insert()
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
