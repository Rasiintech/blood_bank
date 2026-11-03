// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Donor Screening", {
	setup(frm) {
		frm.set_query("donor", () => ({ filters: { status: ["!=", "Permanently Deferred"] } }));
		frm.set_query("blood_request", () => ({ filters: { docstatus: 1, status: ["not in", ["Completed", "Cancelled"]] } }));
		frm.set_query("vital_signs", () => ({ filters: { patient: frm.__donor_patient || "", docstatus: ["<", 2] } }));
	},
	refresh(frm) {
		if (frm.doc.result) {
			frm.page.set_indicator(__(frm.doc.result), frm.doc.result === "Accepted" ? "green" : "red");
		}
		frm.trigger("show_limits");
		if (frm.doc.docstatus === 1 && frm.doc.result === "Accepted") frm.trigger("next_step");
	},
	show_limits(frm) {
		// Show the acceptable range under each vital sign so staff know what decides Accept / Defer
		frappe.call("blood_bank.blood_bank.doctype.blood_donor_screening.blood_donor_screening.get_limits", { donor: frm.doc.donor })
			.then(r => {
				const l = r.message || {};
				const set = (f, txt) => frm.set_df_property(f, "description", txt);
				set("weight_kg", __("Accept: {0} kg or more", [l.weight]));
				set("bp_systolic", __("Accept: {0} to {1} mmHg", l.systolic || []));
				set("bp_diastolic", __("Accept: {0} to {1} mmHg", l.diastolic || []));
				set("pulse", __("Accept: {0} to {1} per minute", l.pulse || []));
				set("temperature", __("Accept: up to {0} °C", [l.temperature]));
				set("hb_g_dl", l.hb ? __("Accept: {0} g/dL or more (optional here; the lab result is used)", [l.hb])
					: __("Optional here; the lab result is used"));
			});
	},
	next_step(frm) {
		frappe.db.get_single_value("Blood Bank Settings", "testing_mode").then(mode => {
			if (mode === "Test the Bag") {
				frappe.call("blood_bank.blood_bank.doctype.blood_donation.blood_donation.donation_status",
					{ donor: frm.doc.donor, donor_screening: frm.doc.name }).then(r => {
					const st = r.message || {};
					if (st.existing) {
						frm.add_custom_button(__("Open Donation"), () => frappe.set_route("Form", "Blood Donation", st.existing)).addClass("btn-primary");
					} else if (st.blocked) {
						frm.dashboard.add_comment(st.blocked, "red", true);
					} else {
						frm.add_custom_button(__("Next: Donation"), () => {
							frappe.new_doc("Blood Donation", { donor: frm.doc.donor, donor_screening: frm.doc.name });
						}).addClass("btn-primary");
					}
				});
				return;
			}
			frm.call("sync_donor_test").then(r => {
				const st = r.message || {};
				const docs = st.lab_documents || [];
				const ordered = frm.doc.sample_collection || frm.doc.sales_invoice;
				const lab_line = docs.map(d => `${d.name}: ${d.docstatus === 1 ? __("Submitted") : __("Not submitted yet")}`).join(", ");
				if (st.donor_test) {
					frappe.db.get_value("Blood Donor Test", st.donor_test, "docstatus").then(t => {
						const done = (t.message || {}).docstatus === 1;
						frm.add_custom_button(__("Open Donor Test"), () => frappe.set_route("Form", "Blood Donor Test", st.donor_test)).addClass("btn-primary");
						frm.dashboard.add_comment(done
							? __("Donor Test {0} is submitted.", [st.donor_test])
							: __("Lab results are in Donor Test {0}. Open it, check and Submit.", [st.donor_test]) + (lab_line ? " (" + lab_line + ")" : ""),
							done ? "green" : "blue", true);
						if (!done) frm.trigger("cancel_order_button");
					});
					return;
				}
				if (!ordered) {
					frm.add_custom_button(__("Next: Order Screening Tests"), () => {
						frm.call("order_screening_tests").then(r => {
							const doc = frappe.model.sync(r.message)[0];
							frappe.set_route("Form", doc.doctype, doc.name);
						});
					}).addClass("btn-primary");
					frm.dashboard.add_comment(__("Order the screening tests (Sample Collection, or an invoice if donors are charged). When the lab submits the Lab Result, the Donor Test is created and filled automatically."), "blue", true);
				} else if (!docs.length) {
					frm.dashboard.add_comment(__("Tests ordered on {0}. No Lab Result made from it yet: submit the Sample Collection so the lab can enter results.", [ordered]), "orange", true);
				} else {
					frm.dashboard.add_comment(__("Tests ordered on {0}. Waiting for the lab to submit: {1}", [ordered, lab_line]), "orange", true);
				}
				if (ordered) frm.trigger("cancel_order_button");
				frm.add_custom_button(__("Enter Results Manually"), () => {
					frappe.new_doc("Blood Donor Test", { donor: frm.doc.donor, donor_screening: frm.doc.name });
				}, __("Create"));
			});
		});
	},
	cancel_order_button(frm) {
		const ordered = frm.doc.sample_collection || frm.doc.sales_invoice;
		if (!ordered) return;
		frm.add_custom_button(__("Cancel Test Order"), () => {
			frappe.confirm(__("Undo the test order {0}? A draft is deleted; a submitted Sample Collection is cancelled with its Lab Results. You can order again afterwards.", [ordered]), () => {
				frm.call("cancel_test_order").then(r => {
					frappe.msgprint((r.message || []).map(frappe.utils.escape_html).join("<br>") || __("Nothing to undo"));
					frm.reload_doc();
				});
			});
		}, __("Actions"));
	},
	donor(frm) {
		if (!frm.doc.donor || frm.doc.docstatus !== 0) return;
		frappe.db.get_value("Blood Donor", frm.doc.donor, "patient").then(r => { frm.__donor_patient = r.message && r.message.patient; });
		frm.call("load_for_donor").then(() => { frm.refresh_fields(); frm.trigger("show_limits"); });
	},
	get_vital_signs(frm) {
		if (!frm.doc.donor) return frappe.msgprint(__("Select the donor first"));
		frm.call("fetch_vital_signs").then(() => frm.refresh_fields());
	},
	blood_request(frm) {
		if (frm.doc.blood_request) {
			frappe.db.get_value("Blood Request", frm.doc.blood_request, "patient")
				.then(r => frm.set_value("replacement_for", r.message.patient));
		}
	},
});
