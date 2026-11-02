// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Donor Test", {
	setup(frm) {
		frm.set_query("donor_screening", () => ({ filters: { donor: frm.doc.donor, docstatus: 1, result: "Accepted" } }));
		frm.set_query("blood_donation", () => ({ filters: { donor: frm.doc.donor, docstatus: 1 } }));
		frm.set_query("lab_reference", () => {
			const p = frm.__lab_patients || [];
			return p.length ? { filters: { patient: ["in", p], docstatus: ["<", 2] } } : {};
		});
	},
	onload(frm) {
		frappe.db.get_single_value("Blood Bank Settings", "testing_mode").then(mode => {
			frm.__bag_mode = mode === "Test the Bag";
			frm.toggle_display("blood_donation", frm.__bag_mode || !!frm.doc.blood_donation);
		});
		if (frm.doc.docstatus === 0 && frm.doc.donor) frm.trigger("prepare");
	},
	donor(frm) { if (frm.doc.docstatus === 0) frm.trigger("prepare"); },
	donor_screening(frm) { if (frm.doc.docstatus === 0) frm.trigger("prepare"); },
	prepare(frm) {
		frm.call("prepare").then(r => {
			frm.__lab_patients = (r.message || {}).patients || [];
			frm.refresh_fields();
		});
	},
	refresh(frm) {
		const colors = { "Non-Reactive": "green", "Reactive": "red", "Incomplete": "orange" };
		if (frm.doc.overall_result) frm.page.set_indicator(__(frm.doc.overall_result), colors[frm.doc.overall_result]);
		if (frm.doc.docstatus === 0 && !frm.doc.lab_reference) {
			frm.set_intro(__("No Lab Result found yet for this donor. Pick it in Lab Reference when the lab has it, or type the results below."), "blue");
		}
		if (frm.doc.docstatus === 1 && frm.doc.overall_result === "Non-Reactive" && !frm.doc.blood_donation) {
			frm.add_custom_button(__("Donation"), () => {
				frappe.new_doc("Blood Donation", { donor: frm.doc.donor, donor_screening: frm.doc.donor_screening, donor_test: frm.doc.name });
			}, __("Create")).addClass("btn-primary");
		}
	},
	fetch_lab_results(frm) {
		if (!frm.doc.lab_reference) {
			frappe.msgprint(__("Select the Lab Result first"));
			return;
		}
		frm.call("fetch_from_lab").then(r => {
			frm.refresh_fields();
			frm.dirty();
			const s = r.message || {};
			let msg = (s.filled || []).map(x => "&#10003; " + frappe.utils.escape_html(x)).join("<br>");
			if ((s.unread || []).length) {
				msg += "<br><br><b>" + __("Could not read, enter manually:") + "</b><br>" + s.unread.map(frappe.utils.escape_html).join("<br>");
			}
			frappe.msgprint({ title: __("Lab Results"), message: msg || __("Nothing matched. Check the test names in Blood Bank Settings."), indicator: (s.unread || []).length ? "orange" : "green" });
		});
	},
});
