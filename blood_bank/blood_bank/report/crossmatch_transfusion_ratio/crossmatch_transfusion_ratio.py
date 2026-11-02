# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	args = {"from": filters.get("from_date") + " 00:00:00", "to": filters.get("to_date") + " 23:59:59"}
	group = "r.medical_department" if filters.get("group_by") == "Department" else "coalesce(r.practitioner_name, r.external_practitioner)"
	rows = frappe.db.sql(f"""
		select {group} as grp,
			count(distinct xi.blood_unit) as crossmatched,
			count(distinct case when t.name is not null then xi.blood_unit end) as transfused
		from `tabBlood Crossmatch` x
		join `tabBlood Crossmatch Item` xi on xi.parent = x.name and xi.result = 'Compatible'
		join `tabBlood Request` r on r.name = x.blood_request
		left join `tabBlood Transfusion` t on t.blood_unit = xi.blood_unit and t.blood_request = r.name and t.docstatus = 1
		where x.docstatus = 1 and x.crossmatch_datetime between %(from)s and %(to)s
		group by grp order by crossmatched desc""", args, as_dict=True)
	for r in rows:
		r.grp = r.grp or _("Not set")
		r.ratio = round(r.crossmatched / r.transfused, 2) if r.transfused else None
	label = _("Department") if filters.get("group_by") == "Department" else _("Doctor")
	columns = [
		{"fieldname": "grp", "label": label, "width": 220},
		{"fieldname": "crossmatched", "label": _("Units Crossmatched"), "fieldtype": "Int", "width": 150},
		{"fieldname": "transfused", "label": _("Units Transfused"), "fieldtype": "Int", "width": 140},
		{"fieldname": "ratio", "label": _("C:T Ratio"), "fieldtype": "Float", "width": 110},
	]
	tc, tt = sum(r.crossmatched for r in rows), sum(r.transfused for r in rows)
	summary = [{"label": _("Overall C:T"), "value": round(tc / tt, 2) if tt else "-", "indicator": "green" if tt and tc / tt <= 2 else "orange"}]
	return columns, rows, _("A C:T ratio above 2.0 usually means blood is crossmatched and not used."), None, summary
