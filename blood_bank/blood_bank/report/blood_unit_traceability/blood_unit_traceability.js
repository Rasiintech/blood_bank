// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Blood Unit Traceability"] = {
	filters: [
		{ fieldname: "blood_unit", label: __("Blood Unit"), fieldtype: "Link", options: "Blood Unit", reqd: 1 },
	],
};
