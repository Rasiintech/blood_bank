import frappe


def execute():
	"""New billing: BB- service items, patient billing settings, crossmatch only for red-cell components,
	donors no longer charged for their screening tests."""
	for dt in ("blood_request_charge", "blood_request", "blood_request_item", "blood_bank_settings", "blood_component",
			"blood_unit", "blood_donor_screening"):
		frappe.reload_doc("blood_bank", "doctype", dt)
	from blood_bank.install import create_billing_items
	changes = create_billing_items(switch_components=True)
	defaults = {"inpatient_billing": "On Issue", "outpatient_billing": "On Request", "submit_charge_invoices": 1,
		"crossmatch_charge": "Separate per crossmatch", "charge_blood_grouping": 1, "non_replacement_fee": "Off",
		"non_replacement_grace_days": 7, "directed_release_days": 3}
	for field, value in defaults.items():
		if frappe.db.get_single_value("Blood Bank Settings", field) in (None, ""):
			frappe.db.set_single_value("Blood Bank Settings", field, value)
	frappe.db.set_single_value("Blood Bank Settings", "charge_replacement_donors", 0)
	frappe.db.set_single_value("Blood Bank Settings", "charge_voluntary_donors", 0)
	frappe.clear_document_cache("Blood Bank Settings", "Blood Bank Settings")
	# open requests made before this change: give them a billing mode; their old invoices are not in the new
	# charges table, so test with new requests
	from blood_bank.billing import billing_mode_for
	for name in frappe.get_all("Blood Request", filters={"docstatus": 1, "billing_mode": ["in", ["", None]]}, pluck="name"):
		req = frappe.get_doc("Blood Request", name)
		frappe.db.set_value("Blood Request", name, "billing_mode", billing_mode_for(req), update_modified=False)
	print("Billing items now used by components:")
	for comp, old, new in changes:
		print(f"  {comp}: {old or '-'} -> {new}")
	print("Enter the prices of the BB- items in Item Price (Standard Selling) before billing.")
