"""Scheduled jobs."""
import frappe
from frappe.utils import now_datetime, nowdate

from blood_bank.utils import update_unit

ACTIVE = ("Quarantine", "Available", "Reserved")


def expire_units():
	"""Hourly: units past expiry can never be used."""
	for name in frappe.get_all("Blood Unit", filters={"status": ["in", ACTIVE],
			"expiry_datetime": ["<=", now_datetime()]}, pluck="name"):
		update_unit(name, status="Expired", remarks="Expired automatically")
		release_request_counts(name)
	frappe.db.commit()


def release_expired_reservations():
	"""Hourly: a crossmatch is only valid for a set time; then the unit returns to stock."""
	for name in frappe.get_all("Blood Unit", filters={"status": "Reserved",
			"reserved_until": ["<=", now_datetime()]}, pluck="name"):
		req = frappe.db.get_value("Blood Unit", name, "blood_request")
		update_unit(name, status="Available", reserved_for=None, blood_request=None, crossmatch=None, reserved_until=None)
		if req:
			refresh_request(req)
	frappe.db.commit()


def end_expired_deferrals():
	"""Daily: temporary deferrals end on their date."""
	for name in frappe.get_all("Blood Donor", filters={"status": "Temporarily Deferred",
			"deferred_until": ["<", nowdate()]}, pluck="name"):
		d = frappe.get_doc("Blood Donor", name)
		d.status = "Active"
		d.flags.ignore_permissions = True
		d.save()
	frappe.db.commit()


def release_request_counts(unit_name):
	req = frappe.db.get_value("Blood Unit", unit_name, "blood_request")
	if req:
		refresh_request(req)


def refresh_request(req_name):
	if frappe.db.get_value("Blood Request", req_name, "docstatus") == 1:
		doc = frappe.get_doc("Blood Request", req_name)
		doc.update_counts_and_status()


def release_directed_units():
	"""Daily: a directed bag goes to general stock after the set days, once its request is closed or the patient left."""
	from frappe.utils import add_days, cint, getdate
	from blood_bank.utils import setting
	days = cint(setting("directed_release_days")) or 3
	for u in frappe.get_all("Blood Unit", filters={"directed_request": ["is", "set"], "status": ["in", ["Quarantine", "Available"]]},
			fields=["name", "directed_request", "collection_datetime"]):
		if getdate(add_days(u.collection_datetime, days)) > getdate(nowdate()):
			continue
		req = frappe.db.get_value("Blood Request", u.directed_request, ["status", "inpatient_record"], as_dict=True) or {}
		discharged = req.get("inpatient_record") and frappe.db.get_value("Inpatient Record", req.inpatient_record, "status") == "Discharged"
		if not req or req.get("status") in ("Completed", "Closed", "Cancelled") or discharged:
			update_unit(u.name, directed_request=None, directed_patient=None,
				remarks="Directed hold ended automatically: request {0} closed or patient discharged".format(u.directed_request))
	frappe.db.commit()
