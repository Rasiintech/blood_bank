// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.listview_settings["Blood Unit"] = {
	add_fields: ["status", "expiry_datetime", "blood_group", "component", "test_status"],
	has_indicator_for_draft: true,
	get_indicator(doc) {
		const colors = { Quarantine: "orange", Available: "green", Reserved: "blue", Issued: "purple",
			Transfused: "gray", Discarded: "red", Expired: "red", Processed: "gray" };
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},
	onload(listview) {
		if (!frappe.user.has_role(["Blood Bank Officer", "System Manager"])) return;
		listview.page.add_actions_menu_item(__("Release to Stock"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) return frappe.msgprint(__("Select units first"));
			frappe.call("blood_bank.blood_bank.doctype.blood_unit.blood_unit.release_units", { units: names })
				.then(r => {
					const res = r.message || {};
					let msg = __("Released: {0}", [(res.released || []).length]);
					if ((res.skipped || []).length) msg += "<br>" + res.skipped.join("<br>");
					frappe.msgprint(msg);
					listview.refresh();
				});
		});
	},
};
