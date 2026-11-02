// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Donor Screening", {
	setup(frm) {
		frm.set_query("donor", () => ({ filters: { status: ["!=", "Permanently Deferred"] } }));
		frm.set_query("blood_request", () => ({ filters: { docstatus: 1, status: ["not in", ["Completed", "Cancelled"]] } }));
	},
	refresh(frm) {
		if (frm.doc.result) {
			frm.page.set_indicator(__(frm.doc.result), frm.doc.result === "Accepted" ? "green" : "red");
		}
		if (frm.doc.docstatus === 1 && frm.doc.result === "Accepted") {
			frm.add_custom_button(__("Donor Test"), () => {
				frappe.new_doc("Blood Donor Test", { donor: frm.doc.donor, donor_screening: frm.doc.name });
			}, __("Create"));
			frm.add_custom_button(__("Donation"), () => {
				frappe.new_doc("Blood Donation", { donor: frm.doc.donor, donor_screening: frm.doc.name });
			}, __("Create"));
		}
	},
	blood_request(frm) {
		if (frm.doc.blood_request) {
			frappe.db.get_value("Blood Request", frm.doc.blood_request, "patient")
				.then(r => frm.set_value("replacement_for", r.message.patient));
		}
	},
});
