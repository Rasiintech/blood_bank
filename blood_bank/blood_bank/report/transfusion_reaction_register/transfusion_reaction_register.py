# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	cond = {"docstatus": 1, "onset_datetime": ["between", [filters.get("from_date") + " 00:00:00", filters.get("to_date") + " 23:59:59"]]}
	if filters.get("severity"):
		cond["severity"] = filters["severity"]
	rows = frappe.get_all("Blood Transfusion Reaction", filters=cond, fields=["name", "onset_datetime", "patient", "patient_name",
		"blood_unit", "reaction_type", "severity", "outcome", "conclusion", "actions_taken"], order_by="onset_datetime desc")
	for r in rows:
		r.component = frappe.db.get_value("Blood Unit", r.blood_unit, "component")
	columns = [
		{"fieldname": "name", "label": _("Reaction"), "fieldtype": "Link", "options": "Blood Transfusion Reaction", "width": 150},
		{"fieldname": "onset_datetime", "label": _("Onset"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "patient_name", "label": _("Patient"), "width": 160},
		{"fieldname": "blood_unit", "label": _("Unit"), "fieldtype": "Link", "options": "Blood Unit", "width": 160},
		{"fieldname": "component", "label": _("Component"), "width": 140},
		{"fieldname": "reaction_type", "label": _("Type"), "width": 180},
		{"fieldname": "severity", "label": _("Severity"), "width": 110},
		{"fieldname": "outcome", "label": _("Outcome"), "width": 110},
		{"fieldname": "conclusion", "label": _("Link to Transfusion"), "width": 130},
	]
	transfused = frappe.db.count("Blood Transfusion", {"docstatus": 1, "end_datetime": cond["onset_datetime"]})
	summary = [{"label": _("Reactions"), "value": len(rows), "indicator": "red"},
		{"label": _("Transfusions"), "value": transfused, "indicator": "blue"},
		{"label": _("Per 1,000 Transfusions"), "value": round(1000.0 * len(rows) / transfused, 1) if transfused else 0, "indicator": "orange"}]
	return columns, rows, None, None, summary
