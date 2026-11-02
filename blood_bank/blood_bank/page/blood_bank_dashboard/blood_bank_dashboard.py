# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_days, add_to_date, cint, get_first_day, now_datetime, nowdate

from blood_bank.utils import BLOOD_GROUPS, setting

OPEN_REQUESTS = ["Requested", "Awaiting Donor", "Crossmatched", "Partially Issued"]


@frappe.whitelist()
def get_data():
	if not frappe.has_permission("Blood Unit", "read"):
		frappe.throw("Not permitted", frappe.PermissionError)
	now = now_datetime()
	warn_days = cint(setting("expiry_warning_days")) or 3
	month_start = get_first_day(nowdate())

	stock_rows = frappe.db.sql("""select component, blood_group, status, count(*) qty from `tabBlood Unit`
		where status in ('Available','Reserved','Quarantine') and expiry_datetime > %s
		group by component, blood_group, status""", now, as_dict=True)
	mins = {(r.component, r.blood_group): r.min_units for r in frappe.get_single("Blood Bank Settings").stock_levels}
	components = frappe.get_all("Blood Component", filters={"disabled": 0}, pluck="name", order_by="is_whole_blood desc, name")
	grid = []
	for comp in components:
		cells = []
		for g in BLOOD_GROUPS:
			avail = sum(r.qty for r in stock_rows if r.component == comp and r.blood_group == g and r.status == "Available")
			cells.append({"group": g, "available": avail, "min": mins.get((comp, g)),
				"short": (comp, g) in mins and avail < mins[(comp, g)]})
		grid.append({"component": comp, "cells": cells})

	def count(dt, filters):
		return frappe.db.count(dt, filters)

	kpis = {
		"available": count("Blood Unit", {"status": "Available", "expiry_datetime": [">", now]}),
		"reserved": count("Blood Unit", {"status": "Reserved"}),
		"ready_to_release": count("Blood Unit", {"status": "Quarantine", "test_status": ["in", ["Cleared", "Not Required"]]}),
		"awaiting_tests": count("Blood Unit", {"status": "Quarantine", "test_status": ["in", ["Pending", "On Hold"]]}),
		"expiring": count("Blood Unit", {"status": ["in", ["Available", "Reserved", "Quarantine"]],
			"expiry_datetime": ["between", [now, add_days(now, warn_days)]]}),
		"open_requests": count("Blood Request", {"docstatus": 1, "status": ["in", OPEN_REQUESTS]}),
		"emergency_today": count("Blood Request", {"docstatus": 1, "urgency": "Emergency", "request_datetime": [">=", nowdate()]}),
		"donations_today": count("Blood Donation", {"docstatus": 1, "collection_datetime": [">=", nowdate()]}),
		"donations_month": count("Blood Donation", {"docstatus": 1, "collection_datetime": [">=", month_start]}),
		"deferred_month": count("Blood Donor Screening", {"docstatus": 1, "result": "Deferred", "screening_datetime": [">=", month_start]}),
		"discarded_month": count("Blood Unit Discard Item", {"parent": ["in", frappe.get_all("Blood Unit Discard",
			filters={"docstatus": 1, "discard_datetime": [">=", month_start]}, pluck="name") or [""]]}),
		"excursions": count("Blood Storage Temperature Log", {"in_range": 0, "reading_datetime": [">=", add_to_date(now, hours=-24)]}),
		"expiry_days": warn_days,
	}
	expiring = frappe.get_all("Blood Unit", filters={"status": ["in", ["Available", "Reserved", "Quarantine"]],
		"expiry_datetime": ["between", [now, add_days(now, warn_days)]]},
		fields=["name", "component", "blood_group", "status", "expiry_datetime"], order_by="expiry_datetime asc", limit=10)
	requests = frappe.db.sql("""select name, patient_name, urgency, status, request_datetime, patient_blood_group
		from `tabBlood Request` where docstatus=1 and status in %(s)s
		order by field(urgency, 'Emergency', 'Urgent', 'Routine'), request_datetime asc limit 10""",
		{"s": OPEN_REQUESTS}, as_dict=True)
	storages = []
	for st in frappe.get_all("Blood Storage", filters={"disabled": 0}, fields=["name", "min_temp", "max_temp"]):
		last = frappe.get_all("Blood Storage Temperature Log", filters={"storage": st.name},
			fields=["temperature", "reading_datetime", "in_range"], order_by="reading_datetime desc", limit=1)
		st.last = last[0] if last else None
		storages.append(st)
	return {"grid": grid, "groups": BLOOD_GROUPS, "kpis": kpis, "expiring": expiring, "requests": requests, "storages": storages}
