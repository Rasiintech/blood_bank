// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Storage Temperature Log", {
	refresh(frm) {
		if (!frm.is_new()) frm.page.set_indicator(frm.doc.in_range ? __("In Range") : __("Out of Range"), frm.doc.in_range ? "green" : "red");
	},
});
