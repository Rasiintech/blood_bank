// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Patient", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Blood Request"), () => frappe.new_doc("Blood Request", { patient: frm.doc.name }), __("Create"));
		frm.add_custom_button(__("Blood Requests"), () => frappe.set_route("List", "Blood Request", { patient: frm.doc.name }), __("View"));
	},
});
