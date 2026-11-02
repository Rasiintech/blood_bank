# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import get_datetime, now_datetime

from blood_bank.utils import setting


class BloodUnitReceipt(Document):
	def validate(self):
		if not (self.supplier or self.source_name):
			frappe.throw(_("Enter the Supplier or where the blood was received from"))
		seen = set()
		for row in self.items:
			if get_datetime(row.expiry_datetime) <= now_datetime():
				frappe.throw(_("Row {0}: unit {1} has already expired").format(row.idx, row.external_unit_number))
			key = (row.external_unit_number or "").strip().upper()
			if key in seen:
				frappe.throw(_("Row {0}: unit {1} is listed twice").format(row.idx, row.external_unit_number))
			seen.add(key)
			dup = frappe.db.get_value("Blood Unit", {"external_unit_number": row.external_unit_number,
				"supplier": self.supplier or "", "status": ["not in", ["Discarded", "Expired", "Transfused"]]}, "name")
			if dup and self.supplier:
				frappe.throw(_("Row {0}: unit {1} from this supplier is already in stock as {2}").format(row.idx, row.external_unit_number, dup))

	def on_submit(self):
		status = setting("received_units_status") or "Available"
		for row in self.items:
			unit = frappe.get_doc({
				"doctype": "Blood Unit",
				"unit_number": make_autoname("RX-.YY.-.#####"),
				"status": status,
				"test_status": "Not Required",
				"component": row.component,
				"blood_group": row.blood_group,
				"volume_ml": row.volume_ml,
				"collection_datetime": row.collection_date,
				"expiry_datetime": row.expiry_datetime,
				"storage": row.storage,
				"source": "Received",
				"blood_unit_receipt": self.name,
				"supplier": self.supplier,
				"external_unit_number": row.external_unit_number,
				"released_by": frappe.session.user if status == "Available" else None,
				"released_on": now_datetime() if status == "Available" else None,
			})
			unit.flags.from_blood_bank = True
			unit.insert(ignore_permissions=True)
			row.db_set("blood_unit", unit.name)

	def on_cancel(self):
		for row in self.items:
			if row.blood_unit:
				status = frappe.db.get_value("Blood Unit", row.blood_unit, "status")
				if status not in ("Quarantine", "Available"):
					frappe.throw(_("Unit {0} is {1}; cannot cancel").format(row.blood_unit, status))
		for row in self.items:
			if row.blood_unit:
				frappe.delete_doc("Blood Unit", row.blood_unit, ignore_permissions=True, force=True)
				row.db_set("blood_unit", None)
