// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Donation", {
	setup(frm) {
		frm.set_query("donor", () => ({ filters: { status: ["!=", "Permanently Deferred"] } }));
		frm.set_query("donor_screening", () => ({ filters: { donor: frm.doc.donor, docstatus: 1, result: "Accepted" } }));
		frm.set_query("donor_test", () => ({ filters: { donor: frm.doc.donor, docstatus: 1, overall_result: "Non-Reactive", blood_donation: ["is", "not set"] } }));
		frm.set_query("storage", () => ({ filters: { disabled: 0 } }));
	},
	onload(frm) {
		frappe.db.get_single_value("Blood Bank Settings", "testing_mode").then(mode => {
			frm.toggle_display("donor_test", mode !== "Test the Bag");
			frm.toggle_reqd("donor_test", mode !== "Test the Bag" && frm.doc.docstatus === 0);
		});
		if (frm.doc.docstatus === 0 && frm.doc.donor_screening && !frm.doc.donor_test) {
			frappe.db.get_list("Blood Donor Test", { filters: { donor_screening: frm.doc.donor_screening, docstatus: 1,
				overall_result: "Non-Reactive" }, fields: ["name"], order_by: "creation desc", limit: 1 })
				.then(rows => { if (rows.length) frm.set_value("donor_test", rows[0].name); });
		}
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
