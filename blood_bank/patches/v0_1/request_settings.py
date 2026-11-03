import frappe


def execute():
	"""Defaults for the new Blood Request settings on sites installed before them."""
	frappe.reload_doc("blood_bank", "doctype", "blood_bank_settings")
	defaults = {
		"replacement_donors_per_unit": 1,
		"lab_values_max_age_days": 3,
		"platelet_labels": "PLT\nPlatelet\nPlatelets\nPlatelet Count",
	}
	for field, value in defaults.items():
		if frappe.db.get_single_value("Blood Bank Settings", field) in (None, "", 0):
			frappe.db.set_single_value("Blood Bank Settings", field, value)
	frappe.clear_document_cache("Blood Bank Settings", "Blood Bank Settings")
