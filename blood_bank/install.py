"""Install / migrate setup: roles, default masters, custom fields."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from blood_bank.utils import BLOOD_GROUPS

ROLES = ["Blood Bank Officer", "Blood Bank Technician", "Blood Bank Reception"]

COMPONENTS = [
	# name, abbr, whole, from_wb, rule, storage, min, max, days, item candidates
	("Whole Blood", "WB", 1, 0, "Identical", "Refrigerator", 2, 6, 35,
		["Blood Transfusion + Cross Matching Whole Blood"]),
	("Red Cells (RBC)", "RBC", 0, 1, "Red Cell", "Refrigerator", 2, 6, 42,
		["Blood transfusion + cross matching (RBC)", "Blood Transfusion + Cross Matching (RBC)"]),
	("Platelets (PLT)", "PLT", 0, 1, "Any", "Platelet Agitator", 20, 24, 5,
		["Blood transfusion + cross matching (PLT)", " Blood transfusion + cross matching (PLT)"]),
	("Fresh Frozen Plasma (FFP)", "FFP", 0, 1, "Plasma", "Freezer", -40, -18, 365,
		["Blood transfusion + cross matching (FFP)", " Blood transfusion + cross matching (FFP)"]),
	("Plasma", "PL", 0, 1, "Plasma", "Freezer", -40, -18, 365,
		["Blood transfusion + cross matching (plasma)", " Blood transfusion + cross matching (plasma)"]),
]

# Defaults to review with the hospital's medical team
DEFERRAL_REASONS = [
	("Low Haemoglobin", "Temporary", 30), ("Underweight", "Temporary", 90),
	("Age Out of Range", "Temporary", 365), ("Blood Pressure Out of Range", "Temporary", 7),
	("Pulse Out of Range", "Temporary", 7), ("Fever / Recent Illness", "Temporary", 14),
	("Donated Too Recently", "Temporary", 0), ("Questionnaire Answer", "Temporary", 30),
	("Antibiotics", "Temporary", 7), ("Aspirin / Painkillers", "Temporary", 5),
	("Tattoo / Piercing", "Temporary", 365), ("Pregnancy / Breastfeeding", "Temporary", 365),
	("Recent Surgery", "Temporary", 365), ("Not Eaten", "Temporary", 0),
	("Malaria (Recent)", "Temporary", 180), ("Reactive Malaria", "Temporary", 180),
	("Reactive HIV", "Permanent", 0), ("Reactive Hepatitis B", "Permanent", 0),
	("Reactive Hepatitis C", "Permanent", 0), ("Reactive Syphilis", "Permanent", 0),
	("Reactive Screening Test", "Permanent", 0), ("Infectious Disease History", "Permanent", 0),
	("High-Risk Behaviour", "Permanent", 0),
]

SCREENING_TESTS = [
	("HIV", 1, "HIV Screening\nHIV\nHIV 1/2", "Reactive HIV"),
	("HBsAg", 1, "HBSAG SCREENING\nHBsAg\nHepatitis B", "Reactive Hepatitis B"),
	("HCV", 1, "ANTI-HCV SCREENING\nHCV\nAnti HCV", "Reactive Hepatitis C"),
	("Syphilis", 1, "Syphilis\nVDRL\nRPR\nTPHA", "Reactive Syphilis"),
	("Malaria", 0, "Malaria\nMalaria RDT\nBS for MPS", "Reactive Malaria"),
]

QUESTIONS = [
	("Do you feel unwell today, or have you had a fever in the last 2 weeks?", "Yes", "Fever / Recent Illness"),
	("Have you eaten in the last 4 hours?", "No", "Not Eaten"),
	("Have you taken antibiotics in the last 7 days?", "Yes", "Antibiotics"),
	("Have you taken aspirin or painkillers in the last 5 days?", "Yes", "Aspirin / Painkillers"),
	("Have you had a tattoo, piercing or acupuncture in the last 12 months?", "Yes", "Tattoo / Piercing"),
	("Are you pregnant, or have you given birth or breastfed in the last 12 months?", "Yes", "Pregnancy / Breastfeeding"),
	("Have you had an operation in the last 12 months?", "Yes", "Recent Surgery"),
	("Have you had malaria in the last 6 months?", "Yes", "Malaria (Recent)"),
	("Have you ever had hepatitis, HIV or syphilis?", "Yes", "Infectious Disease History"),
	("Have you ever injected drugs not prescribed by a doctor?", "Yes", "High-Risk Behaviour"),
]


def before_install():
	create_roles()


def after_install():
	create_roles()
	create_masters()
	setup_settings()
	make_custom_fields()
	from blood_bank.home_tiles import create_home_tiles
	create_home_tiles()
	frappe.db.commit()


def after_migrate():
	create_roles()
	make_custom_fields()
	from blood_bank.home_tiles import create_home_tiles
	create_home_tiles()


def create_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def _find_item(candidates):
	for c in candidates:
		for name in (c, c.strip()):
			if frappe.db.exists("Item", name):
				return name
		found = frappe.db.get_value("Item", {"item_name": c.strip()}, "name")
		if found:
			return found
	return None


def create_masters():
	for name, abbr, whole, from_wb, rule, storage, tmin, tmax, days, items in COMPONENTS:
		if frappe.db.exists("Blood Component", name):
			continue
		frappe.get_doc({
			"doctype": "Blood Component", "component_name": name, "abbreviation": abbr,
			"is_whole_blood": whole, "can_prepare_from_whole_blood": from_wb, "compatibility_rule": rule,
			"storage_type": storage, "min_temp": tmin, "max_temp": tmax, "shelf_life_days": days,
			"billing_item": _find_item(items),
		}).insert(ignore_permissions=True)

	for reason, dtype, days in DEFERRAL_REASONS:
		if not frappe.db.exists("Blood Deferral Reason", reason):
			frappe.get_doc({"doctype": "Blood Deferral Reason", "reason": reason,
				"deferral_type": dtype, "default_days": days}).insert(ignore_permissions=True)

	for test, mandatory, labels, reason in SCREENING_TESTS:
		if not frappe.db.exists("Blood Screening Test", test):
			frappe.get_doc({"doctype": "Blood Screening Test", "test_name": test, "mandatory": mandatory,
				"lab_labels": labels, "deferral_reason": reason}).insert(ignore_permissions=True)

	for storage, stype, tmin, tmax in [("Blood Fridge 1", "Refrigerator", 2, 6),
			("Plasma Freezer 1", "Freezer", -40, -18), ("Platelet Agitator 1", "Platelet Agitator", 20, 24)]:
		if not frappe.db.exists("Blood Storage", storage):
			frappe.get_doc({"doctype": "Blood Storage", "storage_name": storage, "storage_type": stype,
				"min_temp": tmin, "max_temp": tmax}).insert(ignore_permissions=True)


def setup_settings():
	s = frappe.get_single("Blood Bank Settings")
	for df in s.meta.fields:
		if df.default and df.fieldtype not in ("Table", "Section Break", "Column Break") and s.get(df.fieldname) in (None, ""):
			s.set(df.fieldname, df.default)
	if not s.lab_doctype or not frappe.db.exists("DocType", s.lab_doctype):
		s.lab_doctype = next((dt for dt in ("Lab Result", "Lab Test") if frappe.db.exists("DocType", dt)), None)
	if not s.screening_questions:
		for q, ans, reason in QUESTIONS:
			s.append("screening_questions", {"question": q, "defer_if_answer": ans, "deferral_reason": reason})
	if not s.label_hospital_name:
		s.label_hospital_name = frappe.db.get_single_value("Global Defaults", "default_company") or ""
	s.flags.ignore_permissions = True
	s.save()


def make_custom_fields():
	fields = {}
	if frappe.db.exists("DocType", "Sales Invoice"):
		si_meta = frappe.get_meta("Sales Invoice")
		fields["Sales Invoice"] = [{
			"fieldname": "blood_request", "label": "Blood Request", "fieldtype": "Link",
			"options": "Blood Request", "insert_after": "patient" if si_meta.has_field("patient") else "customer",
			"no_copy": 1, "print_hide": 1,
		}]
	if frappe.db.exists("DocType", "Patient") and not frappe.get_meta("Patient").has_field("blood_group"):
		fields["Patient"] = [{
			"fieldname": "bb_blood_group", "label": "Blood Group", "fieldtype": "Select",
			"options": "\n" + "\n".join(BLOOD_GROUPS), "insert_after": "sex",
		}]
	if fields:
		create_custom_fields(fields, update=True)
