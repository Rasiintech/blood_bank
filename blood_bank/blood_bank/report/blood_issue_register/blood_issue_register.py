# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import time_diff_in_seconds


def execute(filters=None):
	filters = filters or {}
	args = {"from": filters.get("from_date") + " 00:00:00", "to": filters.get("to_date") + " 23:59:59"}
	extra = " and i.emergency_release = 1" if filters.get("emergency_only") else ""
	rows = frappe.db.sql(f"""
		select i.name as issue, i.issue_datetime, i.patient, i.patient_name, i.blood_request, r.request_datetime,
			r.urgency, it.blood_unit, it.component, it.blood_group, i.emergency_release, i.received_by, u.status as unit_status
		from `tabBlood Issue` i
		join `tabBlood Issue Item` it on it.parent = i.name
		join `tabBlood Request` r on r.name = i.blood_request
		left join `tabBlood Unit` u on u.name = it.blood_unit
		where i.docstatus = 1 and i.issue_datetime between %(from)s and %(to)s {extra}
		order by i.issue_datetime desc""", args, as_dict=True)
	for r in rows:
		r.turnaround = round(time_diff_in_seconds(r.issue_datetime, r.request_datetime) / 60) if r.request_datetime else None
	columns = [
		{"fieldname": "issue", "label": _("Issue"), "fieldtype": "Link", "options": "Blood Issue", "width": 140},
		{"fieldname": "issue_datetime", "label": _("Issued"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "patient_name", "label": _("Patient"), "width": 160},
		{"fieldname": "blood_unit", "label": _("Unit"), "fieldtype": "Link", "options": "Blood Unit", "width": 160},
		{"fieldname": "component", "label": _("Component"), "width": 150},
		{"fieldname": "blood_group", "label": _("Group"), "width": 100},
		{"fieldname": "urgency", "label": _("Urgency"), "width": 90},
		{"fieldname": "turnaround", "label": _("Request to Issue (min)"), "fieldtype": "Int", "width": 120},
		{"fieldname": "emergency_release", "label": _("Emergency"), "fieldtype": "Check", "width": 90},
		{"fieldname": "received_by", "label": _("Received By"), "width": 120},
		{"fieldname": "unit_status", "label": _("Unit Status"), "width": 100},
		{"fieldname": "blood_request", "label": _("Request"), "fieldtype": "Link", "options": "Blood Request", "width": 130},
	]
	tat = [r.turnaround for r in rows if r.turnaround is not None]
	summary = [{"label": _("Units Issued"), "value": len(rows), "indicator": "blue"},
		{"label": _("Emergency"), "value": len([r for r in rows if r.emergency_release]), "indicator": "red"},
		{"label": _("Avg Turnaround (min)"), "value": round(sum(tat) / len(tat)) if tat else 0, "indicator": "green"}]
	return columns, rows, None, None, summary
