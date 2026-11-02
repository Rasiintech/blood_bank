// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Blood Donation Register"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -1), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "donor_type", label: __("Donor Type"), fieldtype: "Select", options: "\nVoluntary\nReplacement" },
		{ fieldname: "blood_group", label: __("Blood Group"), fieldtype: "Select", options: "\nA Positive\nA Negative\nB Positive\nB Negative\nAB Positive\nAB Negative\nO Positive\nO Negative" },
	],
};
