# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class BloodBankSettings(Document):
	def validate(self):
		if self.lab_doctype and not frappe.db.exists("DocType", self.lab_doctype):
			frappe.throw(_("Lab Doctype {0} does not exist").format(self.lab_doctype))
		pairs = [("min_donor_age", "max_donor_age"), ("min_systolic", "max_systolic"),
			("min_diastolic", "max_diastolic"), ("min_pulse", "max_pulse")]
		for lo, hi in pairs:
			if cint(self.get(lo)) and cint(self.get(hi)) and cint(self.get(lo)) > cint(self.get(hi)):
				frappe.throw(_("{0} cannot be more than {1}").format(self.meta.get_label(lo), self.meta.get_label(hi)))
		seen = set()
		for row in self.stock_levels:
			key = (row.component, row.blood_group)
			if key in seen:
				frappe.throw(_("Stock level for {0} {1} is listed twice").format(*key))
			seen.add(key)
