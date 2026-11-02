# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from blood_bank.utils import OFFICER, update_unit


class BloodTransfusionReaction(Document):
	def validate(self):
		t = frappe.db.get_value("Blood Transfusion", self.blood_transfusion, ["docstatus", "patient", "blood_unit"], as_dict=True)
		if not t or t.docstatus == 2:
			frappe.throw(_("Transfusion {0} is cancelled").format(self.blood_transfusion))
		self.patient = t.patient
		self.blood_unit = t.blood_unit

	def on_submit(self):
		held = self.hold_sibling_units()
		officers = [u for u in frappe.get_all("Has Role", filters={"role": OFFICER, "parenttype": "User"}, pluck="parent")
			if frappe.db.get_value("User", u, "enabled")]
		if officers:
			from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
			enqueue_create_notification(officers, {
				"type": "Alert", "document_type": self.doctype, "document_name": self.name,
				"subject": _("Transfusion reaction ({0}) for {1}, unit {2}").format(self.severity or "-", self.patient_name, self.blood_unit),
			})
		if held:
			frappe.msgprint(_("Other units from the same donation put on hold: {0}").format(", ".join(held)), indicator="orange")

	def hold_sibling_units(self):
		donation = frappe.db.get_value("Blood Unit", self.blood_unit, "blood_donation")
		if not donation:
			return []
		held = []
		for u in frappe.get_all("Blood Unit", filters={"blood_donation": donation, "name": ["!=", self.blood_unit],
				"status": ["in", ["Available", "Quarantine"]]}, pluck="name"):
			update_unit(u, status="Quarantine", test_status="On Hold",
				remarks=_("On hold: reaction {0}").format(self.name))
			held.append(u)
		return held
