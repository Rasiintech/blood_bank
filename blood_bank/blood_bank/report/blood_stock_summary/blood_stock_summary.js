// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Blood Stock Summary"] = {
	filters: [
		{ fieldname: "include_reserved", label: __("Include Reserved"), fieldtype: "Check" },
		{ fieldname: "include_quarantine", label: __("Include Quarantine"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "short" && data && data.short) value = "<span style='color:var(--red-600)'>" + value + "</span>";
		return value;
	},
};
