# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from blood_bank.utils import OFFICER, has_role


def execute(filters=None):
	filters = filters or {}
	columns = [
		{"fieldname": "datetime", "label": _("When"), "fieldtype": "Datetime", "width": 160},
		{"fieldname": "event", "label": _("Event"), "width": 180},
		{"fieldname": "doctype", "label": _("Document Type"), "width": 170, "hidden": 1},
		{"fieldname": "document", "label": _("Document"), "fieldtype": "Dynamic Link", "options": "doctype", "width": 170},
		{"fieldname": "details", "label": _("Details"), "width": 420},
	]
	unit_name = filters.get("blood_unit")
	if not unit_name:
		return columns, []
	u = frappe.get_doc("Blood Unit", unit_name)
	show_donor = has_role(OFFICER)
	ev = []

	def add(when, event, doctype, name, details=""):
		if name:
			ev.append({"datetime": when, "event": event, "doctype": doctype, "document": name, "details": details})

	if u.blood_donation:
		don = frappe.get_doc("Blood Donation", u.blood_donation)
		if show_donor:
			donor = frappe.db.get_value("Blood Donor", don.donor, ["donor_name", "mobile_no"], as_dict=True)
			screened = frappe.db.get_value("Blood Donor Screening", don.donor_screening, "screening_datetime") or don.collection_datetime
			add(screened, _("Donor"), "Blood Donor", don.donor, f"{donor.donor_name} {donor.mobile_no or ''}")
			add(screened, _("Screening"), "Blood Donor Screening", don.donor_screening, "")
			for t in frappe.get_all("Blood Donor Test", filters={"docstatus": 1, "name": ["in", [don.donor_test or "", u.donor_test or ""]]},
					fields=["name", "test_datetime", "overall_result", "blood_group"]):
				add(t.test_datetime, _("Donor Test"), "Blood Donor Test", t.name, f"{t.overall_result}, {t.blood_group}")
		add(don.collection_datetime, _("Collected"), "Blood Donation", don.name, f"{don.volume_ml} ml, {don.bag_type} bag, {don.donor_type}")
	if u.blood_unit_receipt:
		rec = frappe.get_doc("Blood Unit Receipt", u.blood_unit_receipt)
		add(rec.receipt_datetime, _("Received"), "Blood Unit Receipt", rec.name, f"{rec.supplier or rec.source_name}, ext. no. {u.external_unit_number}")
	if u.parent_unit:
		add(u.creation, _("Prepared From"), "Blood Unit", u.parent_unit, u.component_preparation or "")
	for child in frappe.get_all("Blood Unit", filters={"parent_unit": u.name}, fields=["name", "component", "status", "creation"]):
		add(child.creation, _("Component Made"), "Blood Unit", child.name, f"{child.component}: {child.status}")
	if u.released_on:
		add(u.released_on, _("Released to Stock"), "User", u.released_by, "")
	for x in frappe.get_all("Blood Crossmatch Item", filters={"blood_unit": u.name}, fields=["parent", "result"]):
		xm = frappe.db.get_value("Blood Crossmatch", x.parent, ["crossmatch_datetime", "patient_name", "docstatus"], as_dict=True)
		if xm and xm.docstatus == 1:
			add(xm.crossmatch_datetime, _("Crossmatched"), "Blood Crossmatch", x.parent, f"{x.result} for {xm.patient_name}")
	for i in frappe.get_all("Blood Issue Item", filters={"blood_unit": u.name}, fields=["parent"]):
		iss = frappe.db.get_value("Blood Issue", i.parent, ["issue_datetime", "patient_name", "received_by", "emergency_release", "docstatus"], as_dict=True)
		if iss and iss.docstatus == 1:
			add(iss.issue_datetime, _("Issued"), "Blood Issue", i.parent, f"{iss.patient_name}, to {iss.received_by}" + (" (EMERGENCY)" if iss.emergency_release else ""))
	for r in frappe.get_all("Blood Unit Return Item", filters={"blood_unit": u.name}, fields=["parent", "minutes_out", "outcome"]):
		dt = frappe.db.get_value("Blood Unit Return", r.parent, "return_datetime")
		add(dt, _("Returned"), "Blood Unit Return", r.parent, f"{r.minutes_out} min out: {r.outcome}")
	for t in frappe.get_all("Blood Transfusion", filters={"blood_unit": u.name, "docstatus": 1}, fields=["name", "start_datetime", "end_datetime", "patient_name", "outcome", "volume_transfused_ml"]):
		add(t.start_datetime, _("Transfused"), "Blood Transfusion", t.name, f"{t.patient_name}: {t.outcome}, {t.volume_transfused_ml or 0} ml")
	for rx in frappe.get_all("Blood Transfusion Reaction", filters={"blood_unit": u.name, "docstatus": 1}, fields=["name", "onset_datetime", "reaction_type", "severity"]):
		add(rx.onset_datetime, _("Reaction"), "Blood Transfusion Reaction", rx.name, f"{rx.reaction_type} ({rx.severity})")
	if u.blood_unit_discard:
		dt = frappe.db.get_value("Blood Unit Discard", u.blood_unit_discard, "discard_datetime")
		add(dt, _("Discarded"), "Blood Unit Discard", u.blood_unit_discard, u.discard_reason or "")

	# by time; events in the same minute keep the order they happen in the process
	order = [_("Donor"), _("Screening"), _("Donor Test"), _("Collected"), _("Received"), _("Released to Stock"),
		_("Prepared From"), _("Component Made"), _("Crossmatched"), _("Issued"), _("Returned"), _("Transfused"),
		_("Reaction"), _("Discarded")]
	ev.sort(key=lambda e: (str(e["datetime"] or "")[:16], order.index(e["event"]) if e["event"] in order else 99, str(e["datetime"] or "")))
	msg = _("{0}: {1} {2}, status {3}, expiry {4}").format(u.name, u.component, u.blood_group or "", u.status,
		frappe.format(u.expiry_datetime, "Datetime"))
	return columns, ev, msg
