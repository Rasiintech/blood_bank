# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	args = {"from": filters.get("from_date") + " 00:00:00", "to": filters.get("to_date") + " 23:59:59"}
	total = frappe.db.sql("""select count(*) from `tabBlood Donor Screening`
		where docstatus=1 and screening_datetime between %(from)s and %(to)s""", args)[0][0]
	rows = frappe.db.sql("""
		select s.deferral_reason as reason, r.deferral_type, count(*) as qty
		from `tabBlood Donor Screening` s left join `tabBlood Deferral Reason` r on r.name = s.deferral_reason
		where s.docstatus=1 and s.result='Deferred' and s.screening_datetime between %(from)s and %(to)s
		group by s.deferral_reason, r.deferral_type
		union all
		select 'Low Haemoglobin (donor test)' as reason, 'Temporary' as deferral_type, count(*) as qty
		from `tabBlood Donor Test` t
		where t.docstatus=1 and t.hb_ok=0 and t.overall_result='Non-Reactive' and ifnull(t.blood_donation, '')=''
			and t.test_datetime between %(from)s and %(to)s
		having count(*) > 0
		union all
		select concat('Reactive: ', i.screening_test) as reason, 'Permanent' as deferral_type, count(*) as qty
		from `tabBlood Donor Test` t join `tabBlood Donor Test Item` i on i.parent = t.name
		where t.docstatus=1 and i.result='Reactive' and t.test_datetime between %(from)s and %(to)s
		group by i.screening_test
		order by qty desc""", args, as_dict=True)
	for r in rows:
		r.percent = round(100.0 * r.qty / total, 1) if total else 0
	columns = [
		{"fieldname": "reason", "label": _("Reason"), "width": 260},
		{"fieldname": "deferral_type", "label": _("Type"), "width": 110},
		{"fieldname": "qty", "label": _("Donors"), "fieldtype": "Int", "width": 90},
		{"fieldname": "percent", "label": _("% of Screenings"), "fieldtype": "Percent", "width": 130},
	]
	chart = {"data": {"labels": [r.reason for r in rows], "datasets": [{"values": [r.qty for r in rows]}]}, "type": "pie"} if rows else None
	summary = [{"label": _("Screenings"), "value": total, "indicator": "blue"},
		{"label": _("Deferred (temporary)"), "value": sum(r.qty for r in rows if r.deferral_type == "Temporary"), "indicator": "orange"},
		{"label": _("Deferred (permanent)"), "value": sum(r.qty for r in rows if r.deferral_type == "Permanent"), "indicator": "red"}]
	return columns, rows, None, chart, summary
