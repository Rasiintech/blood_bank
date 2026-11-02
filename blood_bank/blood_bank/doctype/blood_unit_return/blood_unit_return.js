// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Unit Return", {
	setup(frm) {
		frm.set_query("blood_issue", () => ({ filters: { docstatus: 1 } }));
		frm.set_query("blood_unit", "items", () => ({ filters: { blood_issue: frm.doc.blood_issue, status: "Issued" } }));
	},
	blood_issue(frm) {
		if (!frm.doc.blood_issue) return;
		frappe.db.get_list("Blood Unit", { filters: { blood_issue: frm.doc.blood_issue, status: "Issued" }, fields: ["name", "component"] })
			.then(rows => {
				frm.clear_table("items");
				rows.forEach(r => Object.assign(frm.add_child("items"), { blood_unit: r.name, component: r.component, seal_intact: 1 }));
				frm.refresh_field("items");
			});
	},
});
