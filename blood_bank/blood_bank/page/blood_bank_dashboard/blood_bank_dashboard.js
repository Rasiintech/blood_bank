// Copyright (c) 2026, Cibaar Technologies and contributors
// For license information, please see license.txt

frappe.pages["blood-bank-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Blood Bank Dashboard"), single_column: true });
	const dash = new BloodBankDashboard(page);
	page.set_primary_action(__("Refresh"), () => dash.refresh(), "refresh");
	page.add_inner_button(__("New Donor"), () => frappe.new_doc("Blood Donor"));
	page.add_inner_button(__("Receive Units"), () => frappe.new_doc("Blood Unit Receipt"));
	page.add_inner_button(__("Temperature Reading"), () => frappe.new_doc("Blood Storage Temperature Log"));
	dash.refresh();
	setInterval(() => { if (frappe.get_route_str() === "blood-bank-dashboard") dash.refresh(); }, 60000);
};

class BloodBankDashboard {
	constructor(page) {
		this.page = page;
		this.$body = $(`<div class="bb-dash"></div>`).appendTo(page.main);
		this.add_style();
	}

	refresh() {
		frappe.call("blood_bank.blood_bank.page.blood_bank_dashboard.blood_bank_dashboard.get_data").then(r => this.render(r.message));
	}

	short(g) { return g.replace(" Positive", "+").replace(" Negative", "−"); }

	render(d) {
		const k = d.kpis;
		const card = (label, value, color, route) =>
			`<div class="bb-card" data-route='${JSON.stringify(route || null)}'>
				<div class="bb-card-value" style="color:var(--${color}-600)">${value}</div>
				<div class="bb-card-label">${label}</div></div>`;
		const cards = [
			card(__("Available Units"), k.available, "green", ["List", "Blood Unit", { status: "Available" }]),
			card(__("Reserved"), k.reserved, "blue", ["List", "Blood Unit", { status: "Reserved" }]),
			card(__("Ready to Release"), k.ready_to_release, k.ready_to_release ? "orange" : "gray", ["List", "Blood Unit", { status: "Quarantine", test_status: ["in", ["Cleared", "Not Required"]] }]),
			card(__("Awaiting Tests / On Hold"), k.awaiting_tests, "gray", ["List", "Blood Unit", { status: "Quarantine" }]),
			card(__("Expiring in {0} days", [k.expiry_days]), k.expiring, k.expiring ? "red" : "gray", ["query-report", "Near Expiry Units"]),
			card(__("Open Requests"), k.open_requests, "purple", ["List", "Blood Request", { docstatus: 1, status: ["in", ["Requested", "Awaiting Donor", "Crossmatched", "Partially Issued"]] }]),
			card(__("Emergency Today"), k.emergency_today, k.emergency_today ? "red" : "gray", ["List", "Blood Request", { urgency: "Emergency" }]),
			card(__("Donations Today / Month"), `${k.donations_today} / ${k.donations_month}`, "blue", ["query-report", "Blood Donation Register"]),
			card(__("Deferred This Month"), k.deferred_month, "orange", ["query-report", "Donor Deferral Analysis"]),
			card(__("Discarded This Month"), k.discarded_month, k.discarded_month ? "red" : "gray", ["query-report", "Blood Wastage Report"]),
			card(__("Temperature Alarms (24h)"), k.excursions, k.excursions ? "red" : "green", ["List", "Blood Storage Temperature Log", { in_range: 0 }]),
		].join("");

		const head = d.groups.map(g => `<th>${this.short(g)}</th>`).join("");
		const rows = d.grid.map(row => {
			const tds = row.cells.map(c => {
				const cls = c.short ? "bb-short" : (c.available ? "bb-ok" : "bb-zero");
				const tip = c.min != null ? __("Minimum {0}", [c.min]) : "";
				return `<td class="${cls}" title="${tip}" data-component="${frappe.utils.escape_html(row.component)}" data-group="${c.group}">${c.available}</td>`;
			}).join("");
			return `<tr><td class="bb-comp">${frappe.utils.escape_html(row.component)}</td>${tds}</tr>`;
		}).join("");

		const exp = d.expiring.length ? d.expiring.map(u =>
			`<tr><td><a href="/app/blood-unit/${encodeURIComponent(u.name)}">${u.name}</a></td><td>${frappe.utils.escape_html(u.component)}</td>
			<td>${this.short(u.blood_group || "")}</td><td>${__(u.status)}</td><td>${frappe.datetime.prettyDate(u.expiry_datetime)}</td></tr>`).join("")
			: `<tr><td colspan="5" class="text-muted">${__("Nothing expiring soon")}</td></tr>`;
		const req = d.requests.length ? d.requests.map(r =>
			`<tr class="${r.urgency === "Emergency" ? "bb-emergency" : ""}"><td><a href="/app/blood-request/${r.name}">${r.name}</a></td>
			<td>${frappe.utils.escape_html(r.patient_name || "")}</td><td>${this.short(r.patient_blood_group || "?")}</td>
			<td>${__(r.urgency)}</td><td>${__(r.status)}</td></tr>`).join("")
			: `<tr><td colspan="5" class="text-muted">${__("No open requests")}</td></tr>`;
		const st = d.storages.map(s => {
			const last = s.last;
			const color = !last ? "gray" : (last.in_range ? "green" : "red");
			const text = last ? `${last.temperature} °C · ${frappe.datetime.prettyDate(last.reading_datetime)}` : __("No reading");
			return `<div class="bb-storage"><span class="indicator-pill ${color}">${frappe.utils.escape_html(s.name)}</span>
				<span class="text-muted">${text} (${s.min_temp ?? ""} to ${s.max_temp ?? ""} °C)</span></div>`;
		}).join("");

		this.$body.html(`
			<div class="bb-cards">${cards}</div>
			<div class="bb-section"><h5>${__("Available Stock by Group")}</h5>
				<div class="table-responsive"><table class="table table-bordered bb-grid"><thead><tr><th>${__("Component")}</th>${head}</tr></thead>
				<tbody>${rows}</tbody></table></div>
				<div class="text-muted small">${__("Red = below the minimum set in Blood Bank Settings. Click a number to open the units.")}</div></div>
			<div class="row">
				<div class="col-md-6 bb-section"><h5>${__("Open Requests")}</h5><table class="table table-sm">${req}</table></div>
				<div class="col-md-6 bb-section"><h5>${__("Expiring Soon")}</h5><table class="table table-sm">${exp}</table></div>
			</div>
			<div class="bb-section"><h5>${__("Storage")}</h5>${st || `<span class="text-muted">${__("No storage set up")}</span>`}</div>`);

		this.$body.find(".bb-card").on("click", function () {
			const route = $(this).data("route");
			if (route) frappe.set_route(...route);
		});
		this.$body.find(".bb-grid td[data-group]").on("click", function () {
			frappe.set_route("List", "Blood Unit", { component: $(this).data("component"), blood_group: $(this).data("group"), status: "Available" });
		});
	}

	add_style() {
		if ($("#bb-dash-style").length) return;
		$(`<style id="bb-dash-style">
			.bb-cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:12px; margin-bottom:20px; }
			.bb-card { background:var(--card-bg); border:1px solid var(--border-color); border-radius:8px; padding:14px; cursor:pointer; }
			.bb-card:hover { border-color:var(--gray-500); }
			.bb-card-value { font-size:24px; font-weight:600; }
			.bb-card-label { color:var(--text-muted); font-size:12px; margin-top:4px; }
			.bb-section { margin-bottom:20px; }
			.bb-grid th, .bb-grid td { text-align:center; }
			.bb-grid td.bb-comp { text-align:left; font-weight:500; }
			.bb-grid td[data-group] { cursor:pointer; font-weight:600; }
			.bb-ok { background:var(--green-50); color:var(--green-700); }
			.bb-zero { color:var(--gray-400); }
			.bb-short { background:var(--red-50); color:var(--red-600); }
			.bb-emergency td { color:var(--red-600); font-weight:600; }
			.bb-storage { margin:6px 0; display:flex; gap:10px; align-items:center; }
		</style>`).appendTo("head");
	}
}
