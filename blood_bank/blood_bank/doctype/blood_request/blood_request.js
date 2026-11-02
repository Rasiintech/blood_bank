// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

const REQUEST_COLORS = { Draft: "red", Requested: "orange", "Awaiting Donor": "orange", Crossmatched: "blue",
	"Partially Issued": "purple", Issued: "purple", Completed: "green", Cancelled: "gray" };

frappe.ui.form.on("Blood Request", {
	setup(frm) {
		frm.set_query("inpatient_record", () => ({ filters: { patient: frm.doc.patient } }));
		frm.set_query("encounter", () => ({ filters: { patient: frm.doc.patient } }));
		frm.set_query("sales_invoice", () => ({ filters: { patient: frm.doc.patient, docstatus: 1 } }));
		frm.set_query("component", "items", () => ({ filters: { disabled: 0 } }));
	},
	patient(frm) {
		if (!frm.doc.patient) return;
		frappe.db.get_value("Patient", frm.doc.patient, "blood_group").then(r => {
			if (r.message && r.message.blood_group) frm.set_value("patient_blood_group", r.message.blood_group);
		});
		frappe.db.get_list("Inpatient Record", { filters: { patient: frm.doc.patient, status: "Admitted" }, fields: ["name"], limit: 1 })
			.then(rows => { if (rows.length) frm.set_value("inpatient_record", rows[0].name); });
	},
	refresh(frm) {
		frm.page.set_indicator(__(frm.doc.status), REQUEST_COLORS[frm.doc.status] || "gray");
		if (frm.doc.docstatus !== 1 || ["Completed", "Cancelled"].includes(frm.doc.status)) return;

		if (!frm.doc.sales_invoice || frm.doc.invoice_status === "Cancelled") {
			frm.add_custom_button(__("Sales Invoice"), () => {
				frappe.call("blood_bank.billing.make_sales_invoice", { blood_request: frm.doc.name }).then(r => {
					const doc = frappe.model.sync(r.message)[0];
					frappe.set_route("Form", doc.doctype, doc.name);
				});
			}, __("Create"));
		}
		frm.add_custom_button(__("Crossmatch"), () => {
			frappe.new_doc("Blood Crossmatch", { blood_request: frm.doc.name, patient_blood_group: frm.doc.patient_blood_group });
		}, __("Create"));
		frm.add_custom_button(__("Issue Blood"), () => {
			frappe.new_doc("Blood Issue", { blood_request: frm.doc.name });
		}, __("Create"));
		frm.add_custom_button(__("Replacement Donor Screening"), () => {
			frappe.new_doc("Blood Donor Screening", { donor_type: "Replacement", replacement_for: frm.doc.patient, blood_request: frm.doc.name });
		}, __("Create"));

		if (frm.doc.invoice_status) {
			frm.dashboard.add_comment(__("Invoice {0}: {1}", [frm.doc.sales_invoice, __(frm.doc.invoice_status)]),
				frm.doc.invoice_status === "Paid" ? "green" : "orange", true);
		} else if (frm.doc.urgency !== "Emergency") {
			frm.dashboard.add_comment(__("Not billed yet: create the Sales Invoice before issuing blood"), "orange", true);
		}
		if (frm.doc.replacement_donors_needed) {
			frm.dashboard.add_comment(__("Replacement donors: {0} of {1}", [frm.doc.replacement_donations || 0, frm.doc.replacement_donors_needed]), "blue", true);
		}
	},
});
