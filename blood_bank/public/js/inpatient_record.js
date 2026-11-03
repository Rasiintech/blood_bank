// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

// Ward orders blood for an admitted patient.
frappe.ui.form.on("Inpatient Record", {
	refresh(frm) {
		if (frm.is_new() || !frappe.model.can_create("Blood Request")) return;
		if (["Admitted", "Admission Scheduled"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Blood Request"), () => frappe.new_doc("Blood Request", {
				patient: frm.doc.patient,
				practitioner: frm.doc.primary_practitioner,
				inpatient_record: frm.doc.name,
				medical_department: frm.doc.medical_department,
			}), __("Create"));
		}
		frm.add_custom_button(__("Blood Requests"), () => frappe.set_route("List", "Blood Request", { inpatient_record: frm.doc.name }), __("View"));
	},
});
