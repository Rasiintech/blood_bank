"""Fill the donor Lab Tests to Order from the site's existing Lab Test Templates."""
import frappe

from blood_bank.install import add_default_lab_tests


def execute():
	frappe.reload_doc("blood_bank", "doctype", "blood_donor_lab_test")
	frappe.reload_doc("blood_bank", "doctype", "blood_bank_settings")
	s = frappe.get_single("Blood Bank Settings")
	if not s.donor_lab_tests:
		add_default_lab_tests(s)
	# Hb usually comes from the CBC line "HGB"
	labels = [l.strip() for l in (s.hb_labels or "").splitlines() if l.strip()]
	if "HGB" not in [l.upper() for l in labels]:
		s.hb_labels = "\n".join(labels + ["HGB"])
	s.flags.ignore_permissions = True
	s.save()
