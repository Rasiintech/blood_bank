// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Crossmatch", {
	setup(frm) {
		frm.set_query("blood_request", () => ({ filters: { docstatus: 1, status: ["not in", ["Completed", "Cancelled"]] } }));
		frm.set_query("blood_unit", "items", () => ({ filters: { status: "Available", test_status: ["in", ["Cleared", "Not Required"]] } }));
	},
	blood_request(frm) {
		if (!frm.doc.blood_request) return;
		frappe.db.get_value("Blood Request", frm.doc.blood_request, "patient_blood_group").then(r => {
			if (r.message && r.message.patient_blood_group) frm.set_value("patient_blood_group", r.message.patient_blood_group);
		});
	},
	get_compatible_units(frm) {
		if (!frm.doc.blood_request) return frappe.msgprint(__("Select the Blood Request first"));
		frappe.call("blood_bank.blood_bank.doctype.blood_crossmatch.blood_crossmatch.get_compatible_units", {
			blood_request: frm.doc.blood_request,
			patient_blood_group: frm.doc.patient_blood_group,
			exclude: (frm.doc.items || []).map(r => r.blood_unit),
		}).then(r => {
			const rows = r.message || [];
			if (!rows.length) return frappe.msgprint(__("No compatible units in stock for what is still needed"));
			rows.forEach(u => {
				const row = frm.add_child("items");
				Object.assign(row, u);
			});
			frm.refresh_field("items");
		});
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.lab_reference) {
			frm.add_custom_button(__("Fetch Result From Lab"), () => frm.call("fetch_from_lab").then(() => { frm.refresh_fields(); frm.dirty(); }));
		}
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Issue Blood"), () => frappe.new_doc("Blood Issue", { blood_request: frm.doc.blood_request }), __("Create"));
		}
	},
});
