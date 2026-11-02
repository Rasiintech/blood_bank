// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.listview_settings["Blood Request"] = {
	add_fields: ["status", "urgency"],
	get_indicator(doc) {
		const colors = { Draft: "red", Requested: "orange", "Awaiting Donor": "orange", Crossmatched: "blue",
			"Partially Issued": "purple", Issued: "purple", Completed: "green", Cancelled: "gray" };
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},
};
