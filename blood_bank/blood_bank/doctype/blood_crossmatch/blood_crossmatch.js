// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Crossmatch", {
	setup(frm) {
		frm.set_query("blood_request", () => ({ filters: { docstatus: 1, status: ["not in", ["Completed", "Closed", "Cancelled"]] } }));
		// only bags this patient can receive, for the requested components that need a crossmatch
		frm.set_query("blood_unit", "items", () => ({
			query: "blood_bank.blood_bank.doctype.blood_crossmatch.blood_crossmatch.unit_query",
			filters: {
				blood_request: frm.doc.blood_request || "",
				patient_blood_group: frm.doc.patient_blood_group || "",
				exclude: JSON.stringify((frm.doc.items || []).map(r => r.blood_unit).filter(Boolean)),
			},
		}));
	},
	blood_request(frm) {
		if (!frm.doc.blood_request) return frm.trigger("render_needs");
		frappe.db.get_value("Blood Request", frm.doc.blood_request, "patient_blood_group").then(r => {
			if (r.message && r.message.patient_blood_group) frm.set_value("patient_blood_group", r.message.patient_blood_group);
			frm.trigger("render_needs");
		});
	},
	patient_blood_group(frm) { frm.trigger("render_needs"); },
	render_needs(frm) {
		const field = frm.get_field("needs_html");
		if (!field) return;
		if (!frm.doc.blood_request) return field.$wrapper.html("");
		frappe.call("blood_bank.request_summary.crossmatch_panel", {
			blood_request: frm.doc.blood_request, patient_blood_group: frm.doc.patient_blood_group,
		}).then(r => field.$wrapper.html(r.message || ""));
	},
	get_compatible_units(frm) {
		if (!frm.doc.blood_request) return frappe.msgprint(__("Select the Blood Request first"));
		frappe.call("blood_bank.blood_bank.doctype.blood_crossmatch.blood_crossmatch.get_compatible_units", {
			blood_request: frm.doc.blood_request,
			patient_blood_group: frm.doc.patient_blood_group,
			exclude: (frm.doc.items || []).map(r => r.blood_unit).filter(Boolean),
		}).then(r => {
			const res = r.message || {};
			const rows = res.units || [];
			// drop empty rows the user added by hand
			frm.doc.items = (frm.doc.items || []).filter(r => r.blood_unit);
			frm.doc.items.forEach((r, i) => { r.idx = i + 1; });
			rows.forEach(u => Object.assign(frm.add_child("items"), u));
			frm.refresh_field("items");
			const notes = res.notes || [];
			if (!rows.length) notes.unshift(__("No compatible bag in stock still needs a crossmatch."));
			if (notes.length) frappe.msgprint(notes.map(frappe.utils.escape_html).join("<br>"), __("Get Compatible Units"));
		});
	},
	refresh(frm) {
		frm.trigger("render_needs");
		if (frm.doc.docstatus === 0 && frm.doc.lab_reference) {
			frm.add_custom_button(__("Fetch Result From Lab"), () => frm.call("fetch_from_lab").then(() => { frm.refresh_fields(); frm.dirty(); }));
		}
		if (frm.doc.docstatus === 1) {
			const units = (frm.doc.items || []).filter(r => r.result === "Compatible").map(r => r.blood_unit);
			if (units.length) frappe.db.get_list("Blood Unit", { filters: { name: ["in", units], status: "Reserved" }, fields: ["name"] }).then(rows => {
				if (rows.length) frm.add_custom_button(__("Issue Blood"), () => frappe.new_doc("Blood Issue", { blood_request: frm.doc.blood_request }), __("Create"));
			});
		}
	},
});
