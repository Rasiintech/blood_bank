// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sales Invoice", {
	setup(frm) {
		frm.set_query("blood_request", () => ({ filters: { patient: frm.doc.patient, docstatus: 1 } }));
	},
});
