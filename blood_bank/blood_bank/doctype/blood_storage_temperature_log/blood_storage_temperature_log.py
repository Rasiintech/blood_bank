# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from blood_bank.utils import OFFICER


class BloodStorageTemperatureLog(Document):
	def validate(self):
		lo, hi = frappe.db.get_value("Blood Storage", self.storage, ["min_temp", "max_temp"])
		self.min_temp, self.max_temp = lo, hi
		in_range = True
		if lo is not None and flt(self.temperature) < flt(lo):
			in_range = False
		if hi is not None and flt(self.temperature) > flt(hi):
			in_range = False
		self.in_range = 1 if in_range else 0

	def after_insert(self):
		if self.in_range:
			return
		units = frappe.db.count("Blood Unit", {"storage": self.storage, "status": ["in", ["Available", "Reserved", "Quarantine"]]})
		frappe.msgprint(_("{0} is out of range ({1} °C). {2} units are stored there: the Blood Bank Officer must decide keep or discard.")
			.format(self.storage, self.temperature, units), title=_("Temperature Excursion"), indicator="red")
		officers = frappe.get_all("Has Role", filters={"role": OFFICER, "parenttype": "User"}, pluck="parent")
		if officers:
			from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
			enqueue_create_notification(list(set(officers)), {"type": "Alert", "document_type": self.doctype,
				"document_name": self.name, "subject": _("Temperature excursion: {0} at {1} °C").format(self.storage, self.temperature)})
