"""One-time: remove the tattoo question, mark the pregnancy question Female-only,
and fill default minimum stock levels if none are set."""
import frappe

from blood_bank.install import add_default_stock_levels


def execute():
	if not frappe.db.exists("DocType", "Blood Bank Settings"):
		return
	s = frappe.get_single("Blood Bank Settings")
	s.screening_questions = [q for q in s.screening_questions if "tattoo" not in (q.question or "").lower()]
	for i, q in enumerate(s.screening_questions, start=1):
		q.idx = i
		if "pregnant" in (q.question or "").lower() or "breastf" in (q.question or "").lower():
			q.applies_to = "Female"
		elif not q.get("applies_to"):
			q.applies_to = "All"
	if not s.stock_levels:
		add_default_stock_levels(s)
	s.flags.ignore_permissions = True
	s.save()
