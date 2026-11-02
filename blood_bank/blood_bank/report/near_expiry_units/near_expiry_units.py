# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, cint, now_datetime, time_diff_in_hours


def execute(filters=None):
	filters = filters or {}
	days = cint(filters.get("days")) or 3
	cond = {"status": ["in", ["Available", "Reserved", "Quarantine"]],
		"expiry_datetime": ["between", [now_datetime(), add_days(now_datetime(), days)]]}
	for f in ("component", "blood_group", "storage"):
		if filters.get(f):
			cond[f] = filters[f]
	rows = frappe.get_all("Blood Unit", filters=cond, fields=["name", "component", "blood_group", "status",
		"expiry_datetime", "storage", "reserved_patient_name"], order_by="expiry_datetime asc")
	for r in rows:
		r.hours_left = round(time_diff_in_hours(r.expiry_datetime, now_datetime()), 1)
	columns = [
		{"fieldname": "name", "label": _("Unit"), "fieldtype": "Link", "options": "Blood Unit", "width": 170},
		{"fieldname": "component", "label": _("Component"), "fieldtype": "Link", "options": "Blood Component", "width": 170},
		{"fieldname": "blood_group", "label": _("Group"), "width": 100},
		{"fieldname": "status", "label": _("Status"), "width": 100},
		{"fieldname": "expiry_datetime", "label": _("Expiry"), "fieldtype": "Datetime", "width": 160},
		{"fieldname": "hours_left", "label": _("Hours Left"), "fieldtype": "Float", "width": 100},
		{"fieldname": "storage", "label": _("Storage"), "fieldtype": "Link", "options": "Blood Storage", "width": 150},
		{"fieldname": "reserved_patient_name", "label": _("Reserved For"), "width": 160},
	]
	return columns, rows
