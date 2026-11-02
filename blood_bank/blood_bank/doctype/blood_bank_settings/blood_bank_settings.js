// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Bank Settings", {
	setup(frm) {
		frm.set_query("lab_doctype", () => ({ filters: { istable: 0, issingle: 0 } }));
	},
});
