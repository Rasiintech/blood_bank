"""Shared helpers for the Blood Bank app."""
import re

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, flt, get_datetime, getdate, now_datetime, nowdate

BLOOD_GROUPS = [
	"A Positive", "A Negative", "B Positive", "B Negative",
	"AB Positive", "AB Negative", "O Positive", "O Negative",
]

# Which donor ABO groups a patient may receive
RED_CELL = {"O": {"O"}, "A": {"A", "O"}, "B": {"B", "O"}, "AB": {"AB", "A", "B", "O"}}
PLASMA = {"O": {"O", "A", "B", "AB"}, "A": {"A", "AB"}, "B": {"B", "AB"}, "AB": {"AB"}}

OFFICER = "Blood Bank Officer"
TECH = "Blood Bank Technician"


# ------------------------------------------------------------------ settings
DEFAULTS = {
	"min_donor_age": 18, "max_donor_age": 65, "min_weight_kg": 45,
	"min_hb_male": 13.0, "min_hb_female": 12.5,
	"donation_interval_male": 84, "donation_interval_female": 112,
	"min_systolic": 90, "max_systolic": 149, "min_diastolic": 50, "max_diastolic": 99,
	"min_pulse": 50, "max_pulse": 100, "max_temperature": 37.5,
	"testing_mode": "Test Donor First", "test_validity_hours": 72,
	"received_units_status": "Available", "crossmatch_validity_hours": 72,
	"return_window_minutes": 30, "transfusion_max_hours": 4, "expiry_warning_days": 3,
	"platelet_labels": "PLT\nPlatelet\nPlatelets\nPlatelet Count", "hb_labels": "HB\nHGB\nHaemoglobin\nHemoglobin",
	"lab_values_max_age_days": 3, "replacement_donors_per_unit": 1,
}


def get_settings():
	return frappe.get_cached_doc("Blood Bank Settings")


def setting(key):
	"""Read a setting with a safe default when empty."""
	value = get_settings().get(key)
	if value in (None, "") and key in DEFAULTS:
		return DEFAULTS[key]
	return value


def lines(text):
	return [l.strip() for l in (text or "").splitlines() if l.strip()]


def has_role(*roles):
	user_roles = set(frappe.get_roles())
	return "System Manager" in user_roles or bool(user_roles.intersection(roles))


# ------------------------------------------------------------------ blood groups
def split_group(group):
	"""'AB Negative' -> ('AB', 'Negative')"""
	if not group:
		return None, None
	parts = group.split(" ")
	if len(parts) != 2:
		return None, None
	return parts[0], parts[1]


def parse_blood_group(value):
	"""Read lab text such as 'A+', 'O Rh -ve', 'AB POSITIVE' into 'A Positive'."""
	if not value:
		return None
	s = str(value).upper()
	s = re.sub(r"RH\s*\(?D\)?|RHESUS|GROUP|BLOOD|[()\[\]:]", " ", s)
	s = re.sub(r"\s+", "", s)
	m = re.match(r"^(AB|A|B|O|0)(.*)$", s)
	if not m:
		return None
	abo = "O" if m.group(1) == "0" else m.group(1)
	rest = m.group(2)
	if "NEG" in rest or rest.startswith("-") or "-VE" in rest:
		rh = "Negative"
	elif "POS" in rest or rest.startswith("+") or "+VE" in rest:
		rh = "Positive"
	else:
		return None
	return f"{abo} {rh}"


def check_compatibility(rule, patient_group, unit_group, emergency=False):
	"""Return (allowed, message). message is a warning when allowed, the reason when blocked."""
	u_abo, u_rh = split_group(unit_group)
	p_abo, p_rh = split_group(patient_group)
	if not u_abo:
		return False, _("Unit has no blood group")

	if not p_abo:
		if not emergency:
			return False, _("Patient blood group is unknown")
		# Emergency with unknown group: universal products only
		if rule in ("Red Cell", "Identical"):
			if u_abo != "O":
				return False, _("Emergency release with unknown patient group needs group O")
			msg = None if u_rh == "Negative" else _("O Positive given to a patient of unknown group: O Negative is preferred for females of childbearing age and children")
			return True, msg
		if rule == "Plasma":
			if u_abo != "AB":
				return False, _("Emergency plasma with unknown patient group needs group AB")
			return True, None
		return True, _("Patient group unknown")

	rh_ok = not (p_rh == "Negative" and u_rh == "Positive")

	if rule == "Identical":
		if u_abo != p_abo:
			if emergency and u_abo == "O":
				return True, _("Emergency: group O whole blood given to a group {0} patient").format(p_abo)
			return False, _("Whole blood must be the same ABO group ({0} patient, {1} unit)").format(p_abo, u_abo)
		if not rh_ok:
			return False, _("RhD negative patient cannot receive RhD positive blood")
		return True, None
	if rule == "Red Cell":
		if u_abo not in RED_CELL[p_abo]:
			return False, _("Group {0} patient cannot receive group {1} red cells").format(p_abo, u_abo)
		if not rh_ok:
			return False, _("RhD negative patient cannot receive RhD positive red cells")
		return True, None
	if rule == "Plasma":
		if u_abo not in PLASMA[p_abo]:
			return False, _("Group {0} patient cannot receive group {1} plasma").format(p_abo, u_abo)
		return True, None
	# Any (platelets)
	msg = None
	if u_abo != p_abo:
		msg = _("ABO not identical ({0} patient, {1} unit); group-specific is preferred").format(p_abo, u_abo)
	elif not rh_ok:
		msg = _("RhD positive unit for an RhD negative patient; consider anti-D cover for females")
	return True, msg


def get_patient_blood_group(patient):
	if not patient:
		return None
	field = patient_blood_group_field()
	return frappe.db.get_value("Patient", patient, field) if field else None


def patient_blood_group_field():
	meta = frappe.get_meta("Patient")
	if meta.has_field("blood_group"):
		return "blood_group"
	if meta.has_field("bb_blood_group"):
		return "bb_blood_group"
	return None


def set_patient_blood_group(patient, group):
	"""Fill the patient's blood group if empty; block if it conflicts."""
	if not (patient and group):
		return
	field = patient_blood_group_field()
	if not field:
		return
	current = frappe.db.get_value("Patient", patient, field)
	if current and current != group:
		frappe.throw(_("Patient {0} is recorded as {1} but this document says {2}. Re-group the patient before continuing.")
			.format(patient, current, group), title=_("Blood Group Mismatch"))
	if not current:
		frappe.db.set_value("Patient", patient, field, group)


# ------------------------------------------------------------------ units
def component_expiry(component, start):
	comp = frappe.get_cached_doc("Blood Component", component)
	start = get_datetime(start or now_datetime())
	return add_to_date(start, days=cint(comp.shelf_life_days), hours=cint(comp.shelf_life_hours))


def update_unit(unit, **values):
	"""The only way code should change a Blood Unit's status."""
	doc = frappe.get_doc("Blood Unit", unit) if isinstance(unit, str) else unit
	doc.update(values)
	doc.flags.from_blood_bank = True
	doc.flags.ignore_permissions = True
	doc.save()
	return doc


def is_expired(unit_doc):
	return unit_doc.expiry_datetime and get_datetime(unit_doc.expiry_datetime) <= now_datetime()


def bag_pouches(bag_type):
	return {"Single": 1, "Double": 2, "Triple": 3, "Quadruple": 4}.get(bag_type, 1)


# ------------------------------------------------------------------ donors
def donor_age(donor):
	if donor.date_of_birth:
		dob = getdate(donor.date_of_birth)
		today = getdate(nowdate())
		return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
	return cint(donor.age_years) or None


def donation_interval_days(sex):
	key = "donation_interval_female" if sex == "Female" else "donation_interval_male"
	return cint(setting(key))


def min_hb(sex):
	return flt(setting("min_hb_female" if sex == "Female" else "min_hb_male"))


def defer_donor(donor, reason, source_doc, until=None, notes=None):
	"""Defer a donor. Permanent reasons never expire."""
	reason_doc = frappe.get_cached_doc("Blood Deferral Reason", reason)
	d = frappe.get_doc("Blood Donor", donor)
	if reason_doc.deferral_type == "Permanent":
		status, until = "Permanently Deferred", None
	else:
		status = "Temporarily Deferred"
		until = until or add_days(nowdate(), cint(reason_doc.default_days))
		if d.status == "Permanently Deferred":
			return  # never downgrade a permanent deferral
		if d.deferred_until and getdate(d.deferred_until) > getdate(until):
			until = d.deferred_until
	d.status = status
	d.deferred_until = until
	d.deferral_reason = reason
	d.deferral_source_type = source_doc.doctype
	d.deferral_source = source_doc.name
	if notes:
		d.notes = ((d.notes or "") + "\n" + notes).strip()
	d.flags.ignore_permissions = True
	d.save()


def clear_deferral_from(source_doc):
	"""Undo a deferral when the document that caused it is cancelled."""
	for name in frappe.get_all("Blood Donor", filters={
		"deferral_source_type": source_doc.doctype, "deferral_source": source_doc.name}, pluck="name"):
		d = frappe.get_doc("Blood Donor", name)
		d.status = "Active"
		d.deferred_until = None
		d.deferral_reason = None
		d.deferral_source_type = None
		d.deferral_source = None
		d.flags.ignore_permissions = True
		d.save()


def refresh_donor_stats(donor):
	rows = frappe.get_all("Blood Donation", filters={"donor": donor, "docstatus": 1},
		fields=["collection_datetime"], order_by="collection_datetime desc")
	d = frappe.get_doc("Blood Donor", donor)
	d.total_donations = len(rows)
	if rows:
		last = getdate(rows[0].collection_datetime)
		d.last_donation_date = last
		d.next_eligible_date = add_days(last, donation_interval_days(d.sex))
	else:
		d.last_donation_date = None
		d.next_eligible_date = None
	d.flags.ignore_permissions = True
	d.save()


# ------------------------------------------------------------------ times
def check_time_order(steps, future_minutes=10):
	"""steps: [(label, datetime or None), ...] in the order they must happen. Refuses times out of order or in the
	future (a few minutes allowed for clocks), so reports and turnaround times stay true."""
	from frappe.utils import add_to_date, format_datetime

	latest = add_to_date(now_datetime(), minutes=future_minutes)
	prev = None
	for label, value in steps:
		if not value:
			continue
		value = get_datetime(value)
		if value > latest:
			frappe.throw(_("{0} ({1}) is in the future").format(label, format_datetime(value)), title=_("Check the Time"))
		if prev and value < prev[1]:
			frappe.throw(_("{0} ({1}) cannot be before {2} ({3})").format(label, format_datetime(value), prev[0],
				format_datetime(prev[1])), title=_("Check the Time"))
		prev = (label, value)
