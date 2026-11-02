// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Patient", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Blood Request"), () => frappe.new_doc("Blood Request", { patient: frm.doc.name }), __("Create"));
		if (frappe.model.can_create("Blood Donor") || frappe.model.can_read("Blood Donor")) {
			frm.add_custom_button(__("Blood Donor"), () => {
				frappe.call("blood_bank.blood_bank.doctype.blood_donor.blood_donor.get_or_create_donor", { patient: frm.doc.name })
					.then(r => frappe.set_route("Form", "Blood Donor", r.message));
			}, __("Create"));
		}
		frm.add_custom_button(__("Blood Requests"), () => frappe.set_route("List", "Blood Request", { patient: frm.doc.name }), __("View"));
	},
});
