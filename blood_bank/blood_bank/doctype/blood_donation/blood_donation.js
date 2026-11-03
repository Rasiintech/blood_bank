// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Donation", {
	setup(frm) {
		frm.set_query("donor", () => ({ filters: { status: ["!=", "Permanently Deferred"] } }));
		frm.set_query("donor_screening", () => ({ filters: { donor: frm.doc.donor, docstatus: 1, result: "Accepted" } }));
		frm.set_query("donor_test", () => ({ filters: { donor: frm.doc.donor, docstatus: 1, overall_result: "Non-Reactive", blood_donation: ["is", "not set"] } }));
		frm.set_query("storage", () => ({ filters: { disabled: 0 } }));
	},
	onload(frm) {
		frappe.db.get_single_value("Blood Bank Settings", "testing_mode").then(mode => {
			frm.toggle_display("donor_test", mode !== "Test the Bag");
			frm.toggle_reqd("donor_test", mode !== "Test the Bag" && frm.doc.docstatus === 0);
		});
		if (frm.doc.docstatus === 0 && frm.doc.donor_screening && !frm.doc.donor_test) {
			frappe.db.get_list("Blood Donor Test", { filters: { donor_screening: frm.doc.donor_screening, docstatus: 1,
				overall_result: "Non-Reactive" }, fields: ["name"], order_by: "creation desc", limit: 1 })
				.then(rows => { if (rows.length) frm.set_value("donor_test", rows[0].name); });
		}
	},
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !frm.doc.blood_unit) return;
		frappe.db.get_value("Blood Unit", frm.doc.blood_unit, "status").then(r => {
			const status = (r.message || {}).status;
			if (status === "Processed") {
				// split already: the whole blood bag no longer exists, its components do
				frm.dashboard.add_comment(__("This bag was split into components. Print and manage the component units."), "blue", true);
				frm.add_custom_button(__("Component Units (Print Labels)"), () =>
					frappe.set_route("List", "Blood Unit", { parent_unit: frm.doc.blood_unit })).addClass("btn-primary");
				return;
			}
			if (["Quarantine", "Available", "Reserved", "Issued"].includes(status)) {
				frm.add_custom_button(__("Print Bag Label"), () => frappe.set_route("print", "Blood Unit", frm.doc.blood_unit));
			}
			frm.add_custom_button(__("Whole Blood Unit"), () => frappe.set_route("Form", "Blood Unit", frm.doc.blood_unit), __("View"));
			if (!["Quarantine", "Available"].includes(status)) return;
			frm.trigger("unsplit_actions");
		});
	},
	unsplit_actions(frm) {
		if (frappe.user.has_role("Blood Bank Officer")) {
			frm.add_custom_button(__("Correct Bag Type"), () => {
				frappe.prompt([
					{ fieldname: "bag_type", fieldtype: "Select", label: __("Correct Bag Type"), reqd: 1,
						options: "Single\nDouble\nTriple\nQuadruple", default: frm.doc.bag_type },
					{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
				], (v) => {
					frappe.call("blood_bank.blood_bank.doctype.blood_donation.blood_donation.correct_bag_type",
						{ donation: frm.doc.name, bag_type: v.bag_type, reason: v.reason })
						.then(() => { frappe.show_alert({ message: __("Bag type corrected"), indicator: "green" }); frm.reload_doc(); });
				}, __("Correct Bag Type"), __("Save"));
			}, __("Actions"));
		}
		if (frm.doc.bag_type && frm.doc.bag_type !== "Single") {
			frm.add_custom_button(__("Split into Components"), () => {
				frappe.new_doc("Blood Component Preparation", { source_unit: frm.doc.blood_unit });
			}, __("Create"));
		}
		frappe.db.get_single_value("Blood Bank Settings", "testing_mode").then(mode => {
			if (mode !== "Test the Bag" || frm.doc.donor_test) return;
			frm.add_custom_button(__("Donor Test for this Bag"), () => {
				frappe.new_doc("Blood Donor Test", { donor: frm.doc.donor, donor_screening: frm.doc.donor_screening, blood_donation: frm.doc.name });
			}, __("Create"));
		});
	},
});
