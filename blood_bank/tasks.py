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
