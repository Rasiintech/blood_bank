// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Unit Receipt", {
	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Received Units"), () => frappe.set_route("List", "Blood Unit", { blood_unit_receipt: frm.doc.name }), __("View"));
		}
	},
});
