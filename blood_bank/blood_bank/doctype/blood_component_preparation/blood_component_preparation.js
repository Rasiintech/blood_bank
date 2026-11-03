// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Blood Component Preparation", {
	setup(frm) {
		frm.set_query("source_unit", () => ({ filters: { source: "Donation", status: ["in", ["Quarantine", "Available"]], component: "Whole Blood" } }));
		frm.set_query("component", "items", () => ({ filters: { is_whole_blood: 0, can_prepare_from_whole_blood: 1, disabled: 0 } }));
	},
	onload(frm) {
		if (frm.is_new() && frm.doc.source_unit) frm.trigger("load_plan");
	},
	source_unit(frm) { if (frm.doc.docstatus === 0) frm.trigger("load_plan"); },
	load_plan(frm) {
		if (!frm.doc.source_unit) return;
		frappe.call("blood_bank.blood_bank.doctype.blood_component_preparation.blood_component_preparation.get_split_plan",
			{ source_unit: frm.doc.source_unit }).then(r => {
			const p = r.message || {};
			frm.set_value({ bag_type: p.bag_type, max_components: p.max_components, collected_volume: p.collected_volume });
			frm.trigger("show_plan_note");
			const empty = !(frm.doc.items || []).some(row => row.component);
			if (empty && (p.rows || []).length) {
				frm.clear_table("items");
				p.rows.forEach(x => {
					const row = frm.add_child("items");
					row.component = x.component; row.volume_ml = x.volume_ml; row.storage = x.storage;
				});
				frm.refresh_field("items");
			}
		});
	},
	show_plan_note(frm) {
		if (!frm.doc.bag_type || frm.doc.docstatus !== 0) return;
		if (frm.doc.bag_type === "Single") {
			frm.set_intro(__("This donation was entered as a Single bag: it cannot be split. If a Double/Triple/Quadruple bag was used, an officer corrects it on the Donation (Actions > Correct Bag Type)."), "red");
		} else {
			frm.set_intro(__("{0} bag, {1} ml collected: up to {2} components. The usual split is filled in below; change the volumes to what the bags really weigh.",
				[frm.doc.bag_type, frm.doc.collected_volume, frm.doc.max_components]), "blue");
		}
	},
	refresh(frm) {
		frm.trigger("show_plan_note");
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Component Units (Print Labels)"), () =>
				frappe.set_route("List", "Blood Unit", { component_preparation: frm.doc.name })).addClass("btn-primary");
		}
	},
});
