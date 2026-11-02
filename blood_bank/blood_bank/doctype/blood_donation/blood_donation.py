# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, cint, get_datetime, getdate, now_datetime

from blood_bank.utils import component_expiry, refresh_donor_stats, setting


def whole_blood_component():
	name = frappe.db.get_value("Blood Component", {"is_whole_blood": 1, "disabled": 0}, "name")
	if not name:
		frappe.throw(_("Create a Blood Component with 'Is Whole Blood' ticked"))
	return name


class BloodDonation(Document):
	def validate(self):
		donor = frappe.get_doc("Blood Donor", self.donor)
		if donor.status == "Permanently Deferred":
			frappe.throw(_("Donor is permanently deferred and cannot donate"))
		if donor.status == "Temporarily Deferred" and donor.deferred_until and getdate(donor.deferred_until) >= getdate(self.collection_datetime):
			frappe.throw(_("Donor is deferred until {0}").format(frappe.format(donor.deferred_until, "Date")))
		if donor.next_eligible_date and getdate(self.collection_datetime) < getdate(donor.next_eligible_date):
			frappe.throw(_("Donor is not eligible again until {0}").format(frappe.format(donor.next_eligible_date, "Date")))

		scr = frappe.get_doc("Blood Donor Screening", self.donor_screening)
		if scr.donor != self.donor or scr.docstatus != 1 or scr.result != "Accepted":
			frappe.throw(_("Donor Screening {0} must be a submitted, Accepted screening of this donor").format(scr.name))
		if frappe.db.exists("Blood Donation", {"donor_screening": scr.name, "docstatus": ["<", 2], "name": ["!=", self.name]}):
			frappe.throw(_("Donor Screening {0} is already used by another donation").format(scr.name))
		hours = cint(setting("test_validity_hours")) or 72
		if get_datetime(self.collection_datetime) > add_to_date(get_datetime(scr.screening_datetime), hours=hours):
			frappe.throw(_("Screening {0} is older than {1} hours; screen the donor again").format(scr.name, hours))

		pre = setting("testing_mode") != "Test the Bag"
		if pre:
			if not self.donor_test:
				frappe.throw(_("Testing mode is 'Test Donor First': select the cleared Blood Donor Test"))
			t = frappe.get_doc("Blood Donor Test", self.donor_test)
			if t.donor != self.donor or t.docstatus != 1:
				frappe.throw(_("Blood Donor Test {0} must be a submitted test of this donor").format(t.name))
			if t.overall_result != "Non-Reactive":
				frappe.throw(_("Blood Donor Test {0} is {1}; the donor cannot donate").format(t.name, t.overall_result))
			if not t.hb_ok:
				frappe.throw(_("Hb in test {0} is below the minimum").format(t.name))
			if get_datetime(self.collection_datetime) > add_to_date(get_datetime(t.test_datetime), hours=hours):
				frappe.throw(_("Test {0} is older than {1} hours; test the donor again").format(t.name, hours))
			self.blood_group = t.blood_group
		else:
			self.blood_group = donor.blood_group
		if not self.blood_group and pre:
			frappe.throw(_("Blood group is unknown; record it in the donor test"))
		if cint(self.volume_ml) <= 0:
			frappe.throw(_("Enter the collected volume"))

	def on_submit(self):
		pre = setting("testing_mode") != "Test the Bag"
		auto = cint(setting("auto_release_cleared_units"))
		status = "Available" if (pre and auto) else "Quarantine"
		component = whole_blood_component()
		unit = frappe.get_doc({
			"doctype": "Blood Unit",
			"unit_number": self.name,
			"status": status,
			"test_status": "Cleared" if pre else "Pending",
			"component": component,
			"blood_group": self.blood_group,
			"volume_ml": self.volume_ml,
			"collection_datetime": self.collection_datetime,
			"expiry_datetime": component_expiry(component, self.collection_datetime),
			"storage": self.storage,
			"source": "Donation",
			"blood_donation": self.name,
			"donor": self.donor,
			"donor_test": self.donor_test,
			"released_by": frappe.session.user if status == "Available" else None,
			"released_on": now_datetime() if status == "Available" else None,
		})
		unit.flags.from_blood_bank = True
		unit.insert(ignore_permissions=True)
		self.db_set("blood_unit", unit.name)
		refresh_donor_stats(self.donor)
		if self.blood_request:
			req = frappe.get_doc("Blood Request", self.blood_request)
			if req.docstatus == 1:
				req.update_counts_and_status()

	def on_cancel(self):
		units = frappe.get_all("Blood Unit", filters={"blood_donation": self.name}, fields=["name", "status", "parent_unit"])
		for u in units:
			if u.status not in ("Quarantine", "Available"):
				frappe.throw(_("Unit {0} is {1}; the donation cannot be cancelled").format(u.name, u.status))
		for u in sorted(units, key=lambda x: 0 if x.parent_unit else 1):
			frappe.delete_doc("Blood Unit", u.name, ignore_permissions=True, force=True)
		self.db_set("blood_unit", None)
		refresh_donor_stats(self.donor)
		if self.blood_request and frappe.db.get_value("Blood Request", self.blood_request, "docstatus") == 1:
			frappe.get_doc("Blood Request", self.blood_request).update_counts_and_status()
