// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Transfusion", {
	setup(frm) {
		frm.set_query("blood_issue", () => ({ filters: { docstatus: 1 } }));
		frm.set_query("blood_unit", () => ({ filters: { blood_issue: frm.doc.blood_issue, status: "Issued" } }));
		frm.set_query("second_checker", () => ({ filters: { name: ["!=", frappe.session.user], enabled: 1 } }));
	},
	refresh(frm) {
		if (frm.doc.exceeded_time_limit) frm.dashboard.set_headline_alert(__("Transfusion went past the allowed time from issue"), "orange");
		if (frm.doc.docstatus < 2 && (frm.doc.reaction_observed || (frm.doc.outcome || "").startsWith("Stopped - Reaction")) && !frm.is_new()) {
			frappe.db.get_list("Blood Transfusion Reaction", { filters: { blood_transfusion: frm.doc.name, docstatus: ["<", 2] }, fields: ["name"], limit: 1 }).then(rows => {
				if (rows.length) frm.add_custom_button(__("Open Reaction"), () => frappe.set_route("Form", "Blood Transfusion Reaction", rows[0].name));
				else frm.add_custom_button(__("Record Reaction"), () => frappe.new_doc("Blood Transfusion Reaction", { blood_transfusion: frm.doc.name })).addClass("btn-danger");
			});
		}
	},
	outcome(frm) { if (frm.doc.outcome === "Stopped - Reaction") frm.set_value("reaction_observed", 1); },
});
