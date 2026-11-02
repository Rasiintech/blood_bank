// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Unit", {
	refresh(frm) {
		const colors = { Quarantine: "orange", Available: "green", Reserved: "blue", Issued: "purple",
			Transfused: "gray", Discarded: "red", Expired: "red", Processed: "gray" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		frm.disable_save();
		if (frm.doc.expiry_datetime && ["Quarantine", "Available", "Reserved"].includes(frm.doc.status)) {
			const hours = frappe.datetime.get_hour_diff(frm.doc.expiry_datetime, frappe.datetime.now_datetime());
			if (hours < 72) frm.dashboard.set_headline_alert(__("Expires in {0} hours", [Math.max(hours, 0)]), "red");
		}
		frm.add_custom_button(__("Print Label"), () => frappe.set_route("print", "Blood Unit", frm.doc.name));
		if (frm.doc.status === "Quarantine" && frappe.user.has_role(["Blood Bank Officer", "System Manager"])) {
			frm.add_custom_button(__("Release to Stock"), () => {
				frappe.call("blood_bank.blood_bank.doctype.blood_unit.blood_unit.release_units", { units: [frm.doc.name] })
					.then(r => { show_release_result(r.message); frm.reload_doc(); });
			}).addClass("btn-primary");
		}
		if (["Quarantine", "Available", "Reserved", "Expired"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Discard"), () => {
				frappe.new_doc("Blood Unit Discard", {}, d => {
					const row = frappe.model.add_child(d, "items");
					row.blood_unit = frm.doc.name;
					row.reason = frm.doc.status === "Expired" ? "Expired" : "";
				});
			}, __("Actions"));
		}
		if (frm.doc.source === "Donation" && frm.doc.component && ["Quarantine", "Available"].includes(frm.doc.status)) {
			frappe.db.get_value("Blood Component", frm.doc.component, "is_whole_blood").then(r => {
				if (r.message && r.message.is_whole_blood) {
					frm.add_custom_button(__("Split into Components"), () => {
						frappe.new_doc("Blood Component Preparation", { source_unit: frm.doc.name });
					}, __("Actions"));
				}
			});
		}
		if (["Quarantine", "Available", "Reserved"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Move Storage"), () => {
				frappe.prompt({ fieldname: "storage", fieldtype: "Link", options: "Blood Storage", label: __("Storage"), reqd: 1 }, v => {
					frappe.call("blood_bank.blood_bank.doctype.blood_unit.blood_unit.move_storage", { unit: frm.doc.name, storage: v.storage })
						.then(() => frm.reload_doc());
				}, __("Move to"));
			}, __("Actions"));
		}
		frm.add_custom_button(__("Traceability"), () => {
			frappe.set_route("query-report", "Blood Unit Traceability", { blood_unit: frm.doc.name });
		}, __("View"));
	},
});

function show_release_result(res) {
	res = res || {};
	let msg = "";
	if ((res.released || []).length) msg += __("Released: {0}", [res.released.join(", ")]);
	if ((res.skipped || []).length) msg += "<br>" + __("Not released:") + "<br>" + res.skipped.join("<br>");
	frappe.msgprint(msg || __("Nothing to release"));
}
window.blood_bank_show_release_result = show_release_result;
