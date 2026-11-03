import frappe


def execute():
	"""Component Preparations showed the whole blood bag's status from the moment they were saved."""
	for p in frappe.get_all("Blood Component Preparation", filters={"docstatus": 1}, fields=["name", "source_unit"]):
		status = frappe.db.get_value("Blood Unit", p.source_unit, "status")
		if status:
			frappe.db.set_value("Blood Component Preparation", p.name, "source_status", status, update_modified=False)
