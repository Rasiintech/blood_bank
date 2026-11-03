// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

const REQUEST_COLORS = { Draft: "red", Requested: "orange", "Awaiting Donor": "orange", Crossmatched: "blue",
	"Partially Issued": "purple", Issued: "purple", Completed: "green", Closed: "green", Cancelled: "gray" };

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
		if (!frm.doc.inpatient_record) frappe.db.get_list("Inpatient Record", { filters: { patient: frm.doc.patient, status: "Admitted" }, fields: ["name"], limit: 1 })
			.then(rows => { if (rows.length) frm.set_value("inpatient_record", rows[0].name); });
		if (frm.doc.docstatus === 0) frm.trigger("get_lab_values");
	},
	onload(frm) {
		if (frm.is_new() && frm.doc.patient) {
			frm.trigger("get_lab_values");
			if (!frm.doc.patient_blood_group) frm.trigger("patient");
		}
	},
	get_lab_values(frm) {
		if (!frm.doc.patient || frm.doc.docstatus !== 0) return;
		frm.call("get_lab_values").then(r => {
			frm.refresh_fields();
			const v = r.message || {};
			if (v.hb == null && v.platelets == null) {
				frm.set_df_property("lab_values_from", "description", __("No recent submitted Hb / platelet result for this patient. Order a CBC, or type an outside result."));
			}
		});
	},
	replacement_donors_needed(frm) { frm.__rep_manual = true; },
	suggest_donors(frm) {
		if (frm.__rep_manual || frm.doc.docstatus !== 0) return;
		frm.call("suggest_replacement_donors").then(r => {
			frm.doc.replacement_donors_needed = r.message || 0;
			frm.refresh_field("replacement_donors_needed");
			frm.dirty();
		});
	},
	refresh(frm) {
		frm.page.set_indicator(__(frm.doc.status), REQUEST_COLORS[frm.doc.status] || "gray");
		if (frm.doc.docstatus !== 1) return;
		const info = frm.doc.__onload || {};
		frm.trigger("billing_summary");
		if (info.charges_pending || frappe.user.has_role(["Blood Bank Officer", "Accounts User", "System Manager"])) {
			frm.add_custom_button(__("Update Charges"), () => {
				frappe.call("blood_bank.billing.update_charges", { blood_request: frm.doc.name }).then(r => {
					const s = r.message || {};
					const lines = [].concat(s.charged || [], (s.credited || []).map(c => __("Credited") + ": " + c), s.problems || []);
					frappe.msgprint(lines.map(frappe.utils.escape_html).join("<br>") || __("Charges are up to date"), __("Billing"));
					frm.reload_doc();
				});
			}, __("Actions"));
		}
		if (["Completed", "Closed", "Cancelled"].includes(frm.doc.status)) {
			frm.trigger("nrf_button");
			return;
		}
		const items = frm.doc.items || [];
		const xm = info.xm_components || [];
		const crossmatch_needed = items.some(r => xm.includes(r.component) && (r.units_required || 0) > (r.units_reserved || 0) + (r.units_issued || 0));
		const reserved = items.some(r => (r.units_reserved || 0) > 0);
		const group_only = items.some(r => !xm.includes(r.component) && (r.units_required || 0) > (r.units_issued || 0));
		const not_all_issued = items.some(r => (r.units_required || 0) > (r.units_issued || 0));
		if (crossmatch_needed) {
			frm.add_custom_button(__("Crossmatch"), () => {
				frappe.new_doc("Blood Crossmatch", { blood_request: frm.doc.name, patient_blood_group: frm.doc.patient_blood_group });
			}, __("Create"));
		}
		if (reserved || group_only || (frm.doc.urgency === "Emergency" && not_all_issued)) {
			frm.add_custom_button(__("Issue Blood"), () => frappe.new_doc("Blood Issue", { blood_request: frm.doc.name }), __("Create"));
		}
		if (!frm.doc.replacement_donors_needed || frm.doc.replacement_donors_needed > (frm.doc.replacement_donations || 0)) {
			frm.add_custom_button(__("Replacement Donor Screening"), () => {
				frappe.new_doc("Blood Donor Screening", { donor_type: "Replacement", replacement_for: frm.doc.patient, blood_request: frm.doc.name });
			}, __("Create"));
			frm.add_custom_button(__("Directed Donor Screening"), () => {
				frappe.new_doc("Blood Donor Screening", { donor_type: "Directed", replacement_for: frm.doc.patient, blood_request: frm.doc.name });
			}, __("Create"));
		}
		if (frappe.user.has_role(["Blood Bank Officer", "Physician", "System Manager"])) {
			frm.add_custom_button(__("Close Request"), () => {
				frappe.prompt({ fieldname: "reason", fieldtype: "Small Text", label: __("Why is blood no longer needed?"), reqd: 1,
					description: __("Reserved bags go back to stock. Billing On Request: bags not used are credited.") }, v => {
					frappe.call("blood_bank.billing.close_request", { blood_request: frm.doc.name, reason: v.reason }).then(() => frm.reload_doc());
				}, __("Close Request"), __("Close"));
			}, __("Actions"));
		}
		if (frm.doc.replacement_donors_needed) {
			frm.dashboard.add_comment(__("Replacement donors: {0} of {1}", [frm.doc.replacement_donations || 0, frm.doc.replacement_donors_needed]), "blue", true);
		}
	},
	billing_summary(frm) {
		const parts = [__("Billing {0}", [__(frm.doc.billing_mode || "-")])];
		const billed = (frm.doc.items || []).reduce((n, r) => n + (r.units_billed || 0), 0);
		parts.push(__("{0} bag(s) charged", [billed]));
		parts.push(__("total {0}", [format_currency(frm.doc.total_charged || 0)]));
		if (frm.doc.invoice_status) parts.push(__(frm.doc.invoice_status));
		const pending = (frm.doc.__onload || {}).charges_pending;
		if (pending) parts.push(__("charges not up to date: use Actions > Update Charges"));
		frm.dashboard.add_comment(parts.join(" · "), pending ? "orange" : "green", true);
	},
	nrf_button(frm) {
		const missing = (frm.doc.replacement_donors_needed || 0) - (frm.doc.replacement_donations || 0);
		if (missing > 0 && !frm.doc.nrf_waived && frappe.user.has_role(["Blood Bank Officer", "System Manager"])) {
			frm.add_custom_button(__("Waive Non-Replacement Fee"), () => {
				frappe.prompt({ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }, v => {
					frappe.call("blood_bank.billing.waive_non_replacement_fee", { blood_request: frm.doc.name, reason: v.reason }).then(() => frm.reload_doc());
				}, __("Waive Non-Replacement Fee"), __("Waive"));
			}, __("Actions"));
		}
	},
});

frappe.ui.form.on("Blood Request Item", {
	component(frm) { frm.trigger("suggest_donors"); },
	units_required(frm) { frm.trigger("suggest_donors"); },
	items_remove(frm) { frm.trigger("suggest_donors"); },
});
