# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, now_datetime, time_diff_in_seconds

from blood_bank.utils import setting, update_unit


class BloodUnitReturn(Document):
	def validate(self):
		issue = frappe.get_doc("Blood Issue", self.blood_issue)
		if issue.docstatus != 1:
			frappe.throw(_("Blood Issue {0} is not submitted").format(issue.name))
		self.patient = issue.patient
		issued = [r.blood_unit for r in issue.items]
		window = cint(setting("return_window_minutes")) or 30
		for row in self.items:
			if row.blood_unit not in issued:
				frappe.throw(_("Row {0}: unit {1} was not issued on {2}").format(row.idx, row.blood_unit, issue.name))
			u = frappe.db.get_value("Blood Unit", row.blood_unit, ["status", "blood_issue"], as_dict=True)
			if self.docstatus == 0 and (u.status != "Issued" or u.blood_issue != issue.name):
				frappe.throw(_("Row {0}: unit {1} is {2}").format(row.idx, row.blood_unit, u.status))
			minutes = int(time_diff_in_seconds(self.return_datetime, issue.issue_datetime) // 60)
			row.minutes_out = max(minutes, 0)
			row.outcome = "Returned to Stock" if (row.minutes_out <= window and row.seal_intact) else "Discarded"

	def on_submit(self):
		late = []
		for row in self.items:
			if row.outcome == "Discarded":
				late.append(row.blood_unit)
				continue
			u = frappe.get_doc("Blood Unit", row.blood_unit)
			if u.crossmatch and u.reserved_until and get_datetime(u.reserved_until) > now_datetime():
				update_unit(u, status="Reserved", blood_issue=None, issued_on=None)
			else:
				update_unit(u, status="Available", blood_issue=None, issued_on=None, reserved_for=None,
					blood_request=None, crossmatch=None, reserved_until=None)
		if late:
			from blood_bank.blood_bank.doctype.blood_unit_discard.blood_unit_discard import discard_units
			discard_units(late, "Returned Late", self, remarks=_("Returned after the allowed time or seal broken"))
		req = frappe.db.get_value("Blood Issue", self.blood_issue, "blood_request")
		frappe.get_doc("Blood Request", req).update_counts_and_status()

	def on_cancel(self):
		frappe.throw(_("A return cannot be cancelled. Issue the unit again if needed."))
