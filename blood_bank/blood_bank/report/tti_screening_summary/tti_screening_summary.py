# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	args = {"from": filters.get("from_date") + " 00:00:00", "to": filters.get("to_date") + " 23:59:59"}
	rows = frappe.db.sql("""
		select i.screening_test as test,
			sum(i.result in ('Reactive','Non-Reactive')) as tested,
			sum(i.result = 'Reactive') as reactive
		from `tabBlood Donor Test` t join `tabBlood Donor Test Item` i on i.parent = t.name
		where t.docstatus = 1 and t.test_datetime between %(from)s and %(to)s
		group by i.screening_test order by i.screening_test""", args, as_dict=True)
	for r in rows:
		r.rate = round(100.0 * (r.reactive or 0) / r.tested, 2) if r.tested else 0
	columns = [
		{"fieldname": "test", "label": _("Test"), "fieldtype": "Link", "options": "Blood Screening Test", "width": 160},
		{"fieldname": "tested", "label": _("Tested"), "fieldtype": "Int", "width": 100},
		{"fieldname": "reactive", "label": _("Reactive"), "fieldtype": "Int", "width": 100},
		{"fieldname": "rate", "label": _("Reactive %"), "fieldtype": "Percent", "width": 120},
	]
	chart = {"data": {"labels": [r.test for r in rows], "datasets": [{"name": _("Reactive %"), "values": [r.rate for r in rows]}]},
		"type": "bar", "colors": ["#c0392b"]} if rows else None
	return columns, rows, None, chart
