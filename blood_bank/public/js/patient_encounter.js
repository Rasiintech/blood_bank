// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

// Doctor orders blood from the consultation: the request opens with patient, doctor, department and admission filled in.
frappe.ui.form.on("Patient Encounter", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus === 2 || !frappe.model.can_create("Blood Request")) return;
		frm.add_custom_button(__("Blood Request"), () => frappe.new_doc("Blood Request", {
			patient: frm.doc.patient,
			practitioner: frm.doc.practitioner,
			encounter: frm.doc.name,
			medical_department: frm.doc.medical_department,
			inpatient_record: frm.doc.inpatient_record,
		}), __("Create"));
		frm.add_custom_button(__("Blood Requests"), () => frappe.set_route("List", "Blood Request", { patient: frm.doc.patient }), __("View"));
	},
});
