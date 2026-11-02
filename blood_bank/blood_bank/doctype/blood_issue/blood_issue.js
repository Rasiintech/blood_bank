// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Issue", {
	setup(frm) {
		frm.set_query("blood_request", () => ({ filters: { docstatus: 1, status: ["not in", ["Completed", "Cancelled"]] } }));
		frm.set_query("authorised_by", () => ({ query: "frappe.core.doctype.user.user.user_query", filters: { ignore_user_type: 1 } }));
		frm.set_query("blood_unit", "items", () => {
			if (frm.doc.emergency_release) return { filters: { status: "Available", test_status: ["in", ["Cleared", "Not Required"]] } };
			return { filters: { status: "Reserved", blood_request: frm.doc.blood_request } };
		});
	},
	blood_request(frm) { if (frm.doc.blood_request && !frm.doc.emergency_release) frm.trigger("get_reserved_units"); },
	get_reserved_units(frm) {
		if (!frm.doc.blood_request) return;
		frappe.call("blood_bank.blood_bank.doctype.blood_issue.blood_issue.get_reserved_units", { blood_request: frm.doc.blood_request })
			.then(r => {
				const have = (frm.doc.items || []).map(x => x.blood_unit);
				(r.message || []).filter(u => !have.includes(u.blood_unit)).forEach(u => Object.assign(frm.add_child("items"), u));
				frm.refresh_field("items");
			});
	},
	refresh(frm) {
		if (frm.doc.emergency_release) frm.dashboard.set_headline_alert(__("EMERGENCY RELEASE: uncrossmatched blood"), "red");
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Transfusion Record"), () => {
				const units = (frm.doc.items || []).map(r => r.blood_unit);
				const make = unit => frappe.new_doc("Blood Transfusion", { blood_issue: frm.doc.name, blood_unit: unit });
				if (units.length === 1) return make(units[0]);
				frappe.prompt({ fieldname: "unit", fieldtype: "Select", options: units, label: __("Unit"), reqd: 1 }, v => make(v.unit));
			}, __("Create"));
			frm.add_custom_button(__("Return Unused Units"), () => frappe.new_doc("Blood Unit Return", { blood_issue: frm.doc.name }), __("Create"));
		}
	},
});
