// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Donor", {
	refresh(frm) {
		if (frm.is_new()) return;
		const colors = { "Active": "green", "Temporarily Deferred": "orange", "Permanently Deferred": "red" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		if (frm.doc.status !== "Permanently Deferred") {
			frm.add_custom_button(__("New Screening"), () => {
				frappe.new_doc("Blood Donor Screening", { donor: frm.doc.name, donor_type: frm.doc.default_donor_type });
			}).addClass("btn-primary");
		}
		if (!frm.doc.patient) {
			frm.add_custom_button(__("Create Patient Record"), () => {
				frappe.call("blood_bank.blood_bank.doctype.blood_donor.blood_donor.make_patient", { donor: frm.doc.name })
					.then(() => frm.reload_doc());
			}, __("Actions"));
		}
		if (frm.doc.next_eligible_date) {
			frm.dashboard.add_comment(__("Next eligible to donate: {0}", [frappe.datetime.str_to_user(frm.doc.next_eligible_date)]), "blue", true);
		}
	},
});
