// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Donation", {
	setup(frm) {
		frm.set_query("donor", () => ({ filters: { status: ["!=", "Permanently Deferred"] } }));
		frm.set_query("donor_screening", () => ({ filters: { donor: frm.doc.donor, docstatus: 1, result: "Accepted" } }));
		frm.set_query("donor_test", () => ({ filters: { donor: frm.doc.donor, docstatus: 1, overall_result: "Non-Reactive", blood_donation: ["is", "not set"] } }));
		frm.set_query("storage", () => ({ filters: { disabled: 0 } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !frm.doc.blood_unit) return;
		frm.add_custom_button(__("Print Bag Label"), () => {
			frappe.set_route("print", "Blood Unit", frm.doc.blood_unit);
		});
		frm.add_custom_button(__("Split into Components"), () => {
			frappe.new_doc("Blood Component Preparation", { source_unit: frm.doc.blood_unit });
		}, __("Create"));
		frm.add_custom_button(__("Donor Test for this Bag"), () => {
			frappe.new_doc("Blood Donor Test", { donor: frm.doc.donor, donor_screening: frm.doc.donor_screening, blood_donation: frm.doc.name });
		}, __("Create"));
	},
});
