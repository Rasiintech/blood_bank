import frappe


def execute():
	"""Give every Blood Component its own 'Blood Transfusion + Cross Matching' lab test (skips existing ones)."""
	from blood_bank.install import ensure_component_lab_templates
	created = ensure_component_lab_templates()
	print("Created:", ", ".join(created) or "nothing, every component already has its lab test")
