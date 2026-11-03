// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Component Preparation", {
	setup(frm) {
		frm.set_query("source_unit", () => ({ filters: { source: "Donation", status: ["in", ["Quarantine", "Available"]], component: "Whole Blood" } }));
		frm.set_query("component", "items", () => ({ filters: { is_whole_blood: 0, can_prepare_from_whole_blood: 1, disabled: 0 } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Component Units (Print Labels)"), () =>
				frappe.set_route("List", "Blood Unit", { component_preparation: frm.doc.name })).addClass("btn-primary");
		}
	},
});
