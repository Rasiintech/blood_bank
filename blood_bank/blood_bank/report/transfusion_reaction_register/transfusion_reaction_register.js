// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Transfusion Reaction Register"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -1), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "severity", label: __("Severity"), fieldtype: "Select", options: "\nMild\nModerate\nSevere\nLife-Threatening\nDeath" },
	],
};
