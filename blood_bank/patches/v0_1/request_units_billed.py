import frappe


def execute():
	"""Fill Units Billed on open requests (patient's and replacement donors' invoices)."""
	frappe.reload_doc("blood_bank", "doctype", "blood_request_item")
	from blood_bank.billing import refresh_request_invoice
	for name in frappe.get_all("Blood Request", filters={"docstatus": 1, "status": ["not in", ["Completed", "Cancelled"]]}, pluck="name"):
		refresh_request_invoice(name)
