# Copyright (c) 2026, Cibaar Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, cint, get_datetime

from blood_bank.utils import bag_pouches, component_expiry, is_expired, setting, update_unit


class BloodComponentPreparation(Document):
	def validate(self):
		src = frappe.get_doc("Blood Unit", self.source_unit)
		if not frappe.db.get_value("Blood Component", src.component, "is_whole_blood"):
			frappe.throw(_("Only whole blood units can be split"))
		if src.source != "Donation":
			frappe.throw(_("Received units are stored as they came and cannot be split"))
		if self.docstatus == 0 and src.status not in ("Quarantine", "Available"):
			frappe.throw(_("Unit {0} is {1} and cannot be split").format(src.name, src.status))
		if is_expired(src):
			frappe.throw(_("Unit {0} has expired").format(src.name))
		max_h = cint(setting("max_hours_to_split"))
		if max_h and get_datetime(self.preparation_datetime) > add_to_date(get_datetime(src.collection_datetime), hours=max_h):
			frappe.throw(_("More than {0} hours have passed since collection").format(max_h))

		bag, volume = frappe.db.get_value("Blood Donation", src.blood_donation, ["bag_type", "volume_ml"])
		self.blood_donation = src.blood_donation
		self.bag_type, self.max_components, self.collected_volume = bag, bag_pouches(bag), cint(volume)
		if bag == "Single":
			frappe.throw(_("Donation {0} was collected in a Single bag: it has no extra pouches, so it stays Whole Blood.<br><br>"
				"If a Double/Triple/Quadruple bag was really used, a Blood Bank Officer opens the donation and uses "
				"Actions > Correct Bag Type.").format(src.blood_donation), title=_("Single bag cannot be split"))
		if len(self.items) > bag_pouches(bag):
			frappe.throw(_("Donation {0} was collected in a {1} bag, which can be split into at most {2} component(s), "
				"but {3} rows are listed.<br><br>If the wrong bag type was entered, a Blood Bank Officer can open the donation "
				"and use Actions > Correct Bag Type, then split again.").format(
				src.blood_donation, bag, bag_pouches(bag), len(self.items)), title=_("Too many components for this bag"))
		plasma = [r.component for r in self.items
			if frappe.db.get_value("Blood Component", r.component, "abbreviation") in ("FFP", "PL")]
		if len(plasma) > 1:
			frappe.throw(_("{0} both come from the same plasma of this bag. Choose only one of them (FFP if frozen within hours of collection, otherwise Plasma).").format(", ".join(plasma)),
				title=_("Same plasma listed twice"))
		seen = set()
		for row in self.items:
			comp = frappe.get_cached_doc("Blood Component", row.component)
			if comp.is_whole_blood or not comp.can_prepare_from_whole_blood:
				frappe.throw(_("Row {0}: {1} cannot be prepared from whole blood").format(row.idx, row.component))
			if row.component in seen:
				frappe.throw(_("Row {0}: {1} is listed twice").format(row.idx, row.component))
			seen.add(row.component)
			row.expiry_datetime = component_expiry(row.component, src.collection_datetime)
		self.source_status_before = src.status
		total = sum(cint(r.volume_ml) for r in self.items)
		if volume and total > cint(volume) + 150:
			frappe.msgprint(_("Components total {0} ml but only {1} ml was collected. Check the volumes "
				"(Red Cells may be up to about 100 ml more because of the additive solution).").format(total, volume),
				title=_("Check Volumes"), indicator="orange")

	def on_submit(self):
		src = frappe.get_doc("Blood Unit", self.source_unit)
		for row in self.items:
			abbr = frappe.db.get_value("Blood Component", row.component, "abbreviation")
			unit = frappe.get_doc({
				"doctype": "Blood Unit",
				"unit_number": f"{src.name}-{abbr}",
				"status": src.status,
				"test_status": src.test_status,
				"component": row.component,
				"blood_group": src.blood_group,
				"volume_ml": row.volume_ml,
				"collection_datetime": src.collection_datetime,
				"expiry_datetime": row.expiry_datetime,
				"storage": row.storage,
				"source": "Prepared",
				"blood_donation": src.blood_donation,
				"parent_unit": src.name,
				"component_preparation": self.name,
				"donor": src.donor,
				"donor_test": src.donor_test,
				"released_by": src.released_by,
				"released_on": src.released_on,
			})
			unit.flags.from_blood_bank = True
			unit.insert(ignore_permissions=True)
			row.db_set("blood_unit", unit.name)
		update_unit(src, status="Processed", remarks=_("Split by {0}").format(self.name))
		self.db_set("source_status", "Processed")

	def on_cancel(self):
		for row in self.items:
			if not row.blood_unit:
				continue
			status = frappe.db.get_value("Blood Unit", row.blood_unit, "status")
			if status not in ("Quarantine", "Available"):
				frappe.throw(_("Component unit {0} is {1}; cannot cancel").format(row.blood_unit, status))
		for row in self.items:
			if row.blood_unit:
				frappe.delete_doc("Blood Unit", row.blood_unit, ignore_permissions=True, force=True)
				row.db_set("blood_unit", None)
		update_unit(self.source_unit, status=self.source_status_before or "Quarantine")
		self.db_set("source_status", self.source_status_before or "Quarantine")


# Usual split per bag type: (abbreviation, share of collected volume; None = fixed ml)
SPLIT_PLAN = {
	"Double": [("RBC", 0.55), ("FFP", None)],
	"Triple": [("RBC", 0.55), ("FFP", None), ("PLT", 50)],
	"Quadruple": [("RBC", 0.55), ("FFP", None), ("PLT", 50)],
}


@frappe.whitelist()
def get_split_plan(source_unit):
	"""Bag type, how many components it allows, and the usual rows pre-filled (staff can change them)."""
	src = frappe.db.get_value("Blood Unit", source_unit, ["blood_donation", "status"], as_dict=True) or {}
	bag, volume = frappe.db.get_value("Blood Donation", src.get("blood_donation"), ["bag_type", "volume_ml"]) if src.get("blood_donation") else (None, 0)
	volume = cint(volume)
	rows, used = [], 0
	plan = SPLIT_PLAN.get(bag, [])
	for abbr, share in plan:
		comp = frappe.db.get_value("Blood Component", {"abbreviation": abbr, "disabled": 0},
			["name", "storage_type"], as_dict=True)
		if not comp:
			continue
		if share is None:
			continue
		ml = int(round(volume * share / 10.0) * 10) if isinstance(share, float) else share
		used += ml
		rows.append({"component": comp.name, "volume_ml": ml, "storage": _storage_for(comp.storage_type), "abbr": abbr})
	for abbr, share in plan:
		if share is None:
			comp = frappe.db.get_value("Blood Component", {"abbreviation": abbr, "disabled": 0}, ["name", "storage_type"], as_dict=True)
			if comp:
				rows.insert(1, {"component": comp.name, "volume_ml": max(volume - used, 0), "storage": _storage_for(comp.storage_type), "abbr": abbr})
	return {"bag_type": bag, "max_components": bag_pouches(bag) if bag else 0, "collected_volume": volume, "rows": rows}


def _storage_for(storage_type):
	return frappe.db.get_value("Blood Storage", {"storage_type": storage_type, "disabled": 0}, "name") if storage_type else None
