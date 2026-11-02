# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	args = {"from": filters.get("from_date") + " 00:00:00", "to": filters.get("to_date") + " 23:59:59"}
	rows = frappe.db.sql("""
		select d.name as discard, d.discard_datetime, i.blood_unit, u.component, u.blood_group, u.source, i.reason, i.status_before
		from `tabBlood Unit Discard` d join `tabBlood Unit Discard Item` i on i.parent = d.name
		left join `tabBlood Unit` u on u.name = i.blood_unit
		where d.docstatus = 1 and d.discard_datetime between %(from)s and %(to)s
		order by d.discard_datetime desc""", args, as_dict=True)
	columns = [
		{"fieldname": "discard_datetime", "label": _("Date"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "blood_unit", "label": _("Unit"), "fieldtype": "Link", "options": "Blood Unit", "width": 160},
		{"fieldname": "component", "label": _("Component"), "width": 160},
		{"fieldname": "blood_group", "label": _("Group"), "width": 100},
		{"fieldname": "source", "label": _("Source"), "width": 100},
		{"fieldname": "reason", "label": _("Reason"), "width": 180},
		{"fieldname": "status_before", "label": _("Was"), "width": 100},
		{"fieldname": "discard", "label": _("Discard Doc"), "fieldtype": "Link", "options": "Blood Unit Discard", "width": 140},
	]
	by_reason = {}
	for r in rows:
		by_reason[r.reason] = by_reason.get(r.reason, 0) + 1
	chart = {"data": {"labels": list(by_reason), "datasets": [{"values": list(by_reason.values())}]}, "type": "pie"} if rows else None
	collected = frappe.db.count("Blood Unit", {"creation": ["between", [args["from"], args["to"]]]})
	summary = [{"label": _("Units Discarded"), "value": len(rows), "indicator": "red"},
		{"label": _("Units Added"), "value": collected, "indicator": "blue"},
		{"label": _("Wastage %"), "value": f"{round(100.0 * len(rows) / collected, 1) if collected else 0}%", "indicator": "orange"}]
	return columns, rows, None, chart, summary
