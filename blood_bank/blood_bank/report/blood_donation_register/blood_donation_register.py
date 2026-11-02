# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	cond = {"docstatus": 1, "collection_datetime": ["between", [filters.get("from_date") + " 00:00:00", filters.get("to_date") + " 23:59:59"]]}
	for f in ("donor_type", "blood_group"):
		if filters.get(f):
			cond[f] = filters[f]
	rows = frappe.get_all("Blood Donation", filters=cond, fields=["name", "collection_datetime", "donor", "donor_name", "sex",
		"donor_type", "blood_group", "volume_ml", "bag_type", "replacement_for", "blood_unit", "donor_reaction"],
		order_by="collection_datetime desc")
	for r in rows:
		r.unit_status = frappe.db.get_value("Blood Unit", r.blood_unit, "status") if r.blood_unit else None
	columns = [
		{"fieldname": "name", "label": _("Donation No."), "fieldtype": "Link", "options": "Blood Donation", "width": 140},
		{"fieldname": "collection_datetime", "label": _("Collected"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "donor", "label": _("Donor"), "fieldtype": "Link", "options": "Blood Donor", "width": 110},
		{"fieldname": "donor_name", "label": _("Name"), "width": 160},
		{"fieldname": "sex", "label": _("Sex"), "width": 70},
		{"fieldname": "donor_type", "label": _("Type"), "width": 100},
		{"fieldname": "blood_group", "label": _("Group"), "width": 100},
		{"fieldname": "volume_ml", "label": _("ml"), "fieldtype": "Int", "width": 60},
		{"fieldname": "bag_type", "label": _("Bag"), "width": 80},
		{"fieldname": "replacement_for", "label": _("For Patient"), "fieldtype": "Link", "options": "Patient", "width": 120},
		{"fieldname": "unit_status", "label": _("Bag Status"), "width": 100},
		{"fieldname": "donor_reaction", "label": _("Donor Reaction"), "fieldtype": "Check", "width": 80},
	]
	types = {}
	for r in rows:
		types[r.donor_type] = types.get(r.donor_type, 0) + 1
	summary = [{"label": _("Donations"), "value": len(rows), "indicator": "blue"}] + [
		{"label": k, "value": v, "indicator": "green"} for k, v in types.items()]
	return columns, rows, None, None, summary
