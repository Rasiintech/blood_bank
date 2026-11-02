# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from blood_bank.utils import BLOOD_GROUPS


def execute(filters=None):
	filters = filters or {}
	statuses = ["Available"]
	if filters.get("include_reserved"):
		statuses.append("Reserved")
	if filters.get("include_quarantine"):
		statuses.append("Quarantine")
	counts = frappe.db.sql("""
		select component, blood_group, count(*) as qty from `tabBlood Unit`
		where status in %(statuses)s and expiry_datetime > now()
		group by component, blood_group""", {"statuses": statuses}, as_dict=True)
	stock = {(c.component, c.blood_group): c.qty for c in counts}
	mins = {}
	for row in frappe.get_single("Blood Bank Settings").stock_levels:
		mins[(row.component, row.blood_group)] = row.min_units

	columns = [{"fieldname": "component", "label": _("Component"), "fieldtype": "Link", "options": "Blood Component", "width": 200}]
	for g in BLOOD_GROUPS:
		columns.append({"fieldname": g.replace(" ", "_").lower(), "label": g.replace(" Positive", "+").replace(" Negative", "-"),
			"fieldtype": "Int", "width": 70})
	columns += [{"fieldname": "total", "label": _("Total"), "fieldtype": "Int", "width": 80},
		{"fieldname": "short", "label": _("Below Minimum"), "fieldtype": "Data", "width": 220}]

	data = []
	for comp in frappe.get_all("Blood Component", filters={"disabled": 0}, pluck="name", order_by="is_whole_blood desc, name"):
		row = {"component": comp, "total": 0}
		short = []
		for g in BLOOD_GROUPS:
			qty = stock.get((comp, g), 0)
			row[g.replace(" ", "_").lower()] = qty
			row["total"] += qty
			if (comp, g) in mins and qty < mins[(comp, g)]:
				short.append(f"{g.replace(' Positive', '+').replace(' Negative', '-')} ({qty}/{mins[(comp, g)]})")
		row["short"] = ", ".join(short)
		data.append(row)

	chart = {"data": {"labels": [c["label"] for c in columns[1:9]],
		"datasets": [{"name": _("Units"), "values": [sum(r[c["fieldname"]] for r in data) for c in columns[1:9]]}]},
		"type": "bar", "colors": ["#c0392b"]}
	return columns, data, None, chart
