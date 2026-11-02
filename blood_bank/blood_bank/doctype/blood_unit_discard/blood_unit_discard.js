// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Unit Discard", {
	setup(frm) {
		frm.set_query("blood_unit", "items", () => ({ filters: { status: ["in", ["Quarantine", "Available", "Reserved", "Expired"]] } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Expired Units"), () => {
				frappe.db.get_list("Blood Unit", { filters: { status: "Expired" }, fields: ["name"], limit: 500 }).then(rows => {
					const have = (frm.doc.items || []).map(r => r.blood_unit);
					rows.filter(r => !have.includes(r.name)).forEach(r => {
						const row = frm.add_child("items");
						row.blood_unit = r.name;
						row.reason = "Expired";
					});
					frm.refresh_field("items");
				});
			});
		}
	},
});
