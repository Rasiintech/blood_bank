// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Issue", {
	setup(frm) {
		frm.set_query("blood_request", () => ({ filters: { docstatus: 1, status: ["not in", ["Completed", "Cancelled"]] } }));
		frm.set_query("authorised_by", () => ({ query: "frappe.core.doctype.user.user.user_query", filters: { ignore_user_type: 1 } }));
		frm.set_query("blood_unit", "items", () => {
			if (frm.doc.emergency_release) return { filters: { status: "Available", test_status: ["in", ["Cleared", "Not Required"]] } };
			// this request's crossmatched bags, and compatible plasma / platelets from stock
			return {
				query: "blood_bank.blood_bank.doctype.blood_issue.blood_issue.unit_query",
				filters: {
					blood_request: frm.doc.blood_request || "",
					exclude: JSON.stringify((frm.doc.items || []).map(r => r.blood_unit).filter(Boolean)),
				},
			};
		});
	},
	blood_request(frm) {
		frm.trigger("render_needs");
		if (frm.doc.blood_request && !frm.doc.emergency_release) frm.trigger("get_reserved_units");
	},
	render_needs(frm) {
		const field = frm.get_field("needs_html");
		if (!field) return;
		if (!frm.doc.blood_request) return field.$wrapper.html("");
		frappe.call("blood_bank.request_summary.issue_panel", { blood_request: frm.doc.blood_request })
			.then(r => field.$wrapper.html(r.message || ""));
	},
	get_reserved_units(frm) {
		if (!frm.doc.blood_request) return;
		frappe.call("blood_bank.blood_bank.doctype.blood_issue.blood_issue.get_reserved_units", { blood_request: frm.doc.blood_request })
			.then(r => {
				// drop the empty row a new form starts with
				frm.doc.items = (frm.doc.items || []).filter(x => x.blood_unit);
				frm.doc.items.forEach((x, i) => { x.idx = i + 1; });
				const have = frm.doc.items.map(x => x.blood_unit);
				const rows = (r.message || []).filter(u => !have.includes(u.blood_unit));
				rows.forEach(u => Object.assign(frm.add_child("items"), u));
				frm.refresh_field("items");
				if (!rows.length && !have.length) frappe.msgprint(__("Nothing ready to issue: crossmatch the red cells first, or check the stock."));
			});
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) frm.trigger("render_needs");
		if (frm.doc.emergency_release) frm.dashboard.set_headline_alert(__("EMERGENCY RELEASE: uncrossmatched blood"), "red");
		if (frm.doc.docstatus === 1) {
			const all = (frm.doc.items || []).map(r => r.blood_unit);
			Promise.all([
				frappe.db.get_list("Blood Unit", { filters: { name: ["in", all], status: "Issued" }, fields: ["name"] }),
				frappe.db.get_list("Blood Transfusion", { filters: { blood_issue: frm.doc.name, docstatus: ["<", 2] }, fields: ["blood_unit"] }),
			]).then(([out, done]) => {
				const recorded = done.map(d => d.blood_unit);
				const units = out.map(u => u.name).filter(u => !recorded.includes(u));
				if (units.length) {
					frm.add_custom_button(__("Transfusion Record"), () => {
						const make = unit => frappe.new_doc("Blood Transfusion", { blood_issue: frm.doc.name, blood_unit: unit });
						if (units.length === 1) return make(units[0]);
						frappe.prompt({ fieldname: "unit", fieldtype: "Select", options: units, label: __("Unit"), reqd: 1 }, v => make(v.unit));
					}, __("Create"));
				}
				if (out.length) {
					frm.add_custom_button(__("Return Unused Units"), () => frappe.new_doc("Blood Unit Return", { blood_issue: frm.doc.name }), __("Create"));
				}
			});
		}
	},
});
