// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Donor", {
	setup(frm) {
		frm.set_query("patient", () => ({ filters: { status: "Active" } }));
	},
	refresh(frm) {
		if (frm.is_new()) {
			frm.set_intro(__("Pick the Patient. If this person has no Patient record yet, create the Patient first."), "blue");
			return;
		}
		const colors = { "Active": "green", "Temporarily Deferred": "orange", "Permanently Deferred": "red" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		if (frm.doc.status !== "Permanently Deferred") {
			frm.add_custom_button(__("New Screening"), () => {
				frappe.new_doc("Blood Donor Screening", { donor: frm.doc.name, donor_type: frm.doc.default_donor_type });
			}).addClass("btn-primary");
		}
		frm.add_custom_button(__("Patient"), () => frappe.set_route("Form", "Patient", frm.doc.patient), __("View"));
		frm.add_custom_button(__("Donations"), () => frappe.set_route("List", "Blood Donation", { donor: frm.doc.name }), __("View"));
		if (frm.doc.next_eligible_date) {
			frm.dashboard.add_comment(__("Next eligible to donate: {0}", [frappe.datetime.str_to_user(frm.doc.next_eligible_date)]), "blue", true);
		}
	},
});
