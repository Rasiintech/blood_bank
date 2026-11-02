// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.listview_settings["Blood Donor"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colors = { "Active": "green", "Temporarily Deferred": "orange", "Permanently Deferred": "red" };
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},
};
