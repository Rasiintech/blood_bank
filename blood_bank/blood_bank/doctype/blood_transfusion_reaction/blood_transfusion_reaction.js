// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Transfusion Reaction", {
	refresh(frm) {
		if (frm.doc.severity && ["Severe", "Life-Threatening", "Death"].includes(frm.doc.severity)) {
			frm.dashboard.set_headline_alert(__("Severe reaction: stop the transfusion, keep the bag, send a fresh patient sample to the blood bank"), "red");
		}
	},
});
