// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Near Expiry Units"] = {
	filters: [
		{ fieldname: "days", label: __("Expiring Within (days)"), fieldtype: "Int", default: 3 },
		{ fieldname: "component", label: __("Component"), fieldtype: "Link", options: "Blood Component" },
		{ fieldname: "blood_group", label: __("Blood Group"), fieldtype: "Select", options: "\nA Positive\nA Negative\nB Positive\nB Negative\nAB Positive\nAB Negative\nO Positive\nO Negative" },
		{ fieldname: "storage", label: __("Storage"), fieldtype: "Link", options: "Blood Storage" },
	],
};
