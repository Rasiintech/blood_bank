# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from blood_bank.utils import setting, update_unit


class BloodTransfusion(Document):
	def validate(self):
		issue = frappe.get_doc("Blood Issue", self.blood_issue)
		if issue.docstatus != 1:
			frappe.throw(_("Blood Issue {0} is not submitted").format(issue.name))
		if self.blood_unit not in [r.blood_unit for r in issue.items]:
			frappe.throw(_("Unit {0} was not issued on {1}").format(self.blood_unit, issue.name), title=_("Wrong Unit"))
		self.patient = issue.patient
		u = frappe.db.get_value("Blood Unit", self.blood_unit, ["status", "blood_issue", "reserved_for"], as_dict=True)
		if self.docstatus == 0 and (u.status != "Issued" or u.blood_issue != issue.name):
			frappe.throw(_("Unit {0} is {1}, not issued for this patient").format(self.blood_unit, u.status), title=_("Wrong Unit"))
		if u.reserved_for and u.reserved_for != self.patient:
			frappe.throw(_("Unit {0} belongs to another patient").format(self.blood_unit), title=_("Wrong Patient"))
		other = frappe.db.get_value("Blood Transfusion", {"blood_unit": self.blood_unit, "docstatus": ["<", 2], "name": ["!=", self.name]})
		if other:
			frappe.throw(_("Unit {0} already has transfusion record {1}").format(self.blood_unit, other))
		if self.second_checker and self.second_checker == self.first_checker:
			frappe.throw(_("The second checker must be a different person"))
		from blood_bank.utils import check_time_order
		check_time_order([(_("Issue"), issue.issue_datetime), (_("Start"), self.start_datetime), (_("End"), self.end_datetime)])
		limit = add_to_date(get_datetime(issue.issue_datetime), hours=cint(setting("transfusion_max_hours")) or 4)
		finish = get_datetime(self.end_datetime) if self.end_datetime else now_datetime()
		self.exceeded_time_limit = 1 if finish > limit else 0
		if self.outcome == "Stopped - Reaction":
			self.reaction_observed = 1

	def before_submit(self):
		if not (self.patient_identity_confirmed and self.unit_label_checked and self.unit_expiry_checked):
			frappe.throw(_("Complete all three bedside checks"))
		if self.outcome == "In Progress" or not self.end_datetime:
			frappe.throw(_("Enter the end time and outcome before submitting"))

	def on_submit(self):
		update_unit(self.blood_unit, status="Transfused", blood_transfusion=self.name, transfused_on=self.end_datetime)
		frappe.get_doc("Blood Request", self.blood_request).update_counts_and_status()
		if self.reaction_observed and not frappe.db.exists("Blood Transfusion Reaction", {"blood_transfusion": self.name, "docstatus": ["<", 2]}):
			frappe.msgprint(_("A reaction was observed. Record it with a Blood Transfusion Reaction."), indicator="red")

	def on_cancel(self):
		if frappe.db.exists("Blood Transfusion Reaction", {"blood_transfusion": self.name, "docstatus": 1}):
			frappe.throw(_("A submitted reaction refers to this transfusion"))
		update_unit(self.blood_unit, status="Issued", blood_transfusion=None, transfused_on=None)
		frappe.get_doc("Blood Request", self.blood_request).update_counts_and_status()
