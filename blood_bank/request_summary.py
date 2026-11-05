"""What a Blood Request needs, which units fit the patient, and which donors came for the request.

Used by the crossmatch (unit dropdown, Get Compatible Units, "What this patient needs" panel) and by the
"Donors for this Request" panel on the Blood Request."""
import frappe
from frappe import _
from frappe.utils import cint, escape_html, now_datetime

from blood_bank.utils import BLOOD_GROUPS, check_compatibility, get_patient_blood_group

USABLE_TESTS = ("Cleared", "Not Required")


def needs_crossmatch(component):
	return bool(cint(frappe.db.get_value("Blood Component", component, "requires_crossmatch")))


def patient_group(req, group=None):
	return group or req.patient_blood_group or get_patient_blood_group(req.patient)


def allowed_groups(component, group):
	"""Donor groups this patient may receive for the component (ABO/Rh rule of the component)."""
	rule = frappe.db.get_value("Blood Component", component, "compatibility_rule")
	return [g for g in BLOOD_GROUPS if check_compatibility(rule, group, g)[0]]


def lab_crossmatches(patient):
	"""Donor Tests whose lab result already crossmatched the donor with this patient (replacement donors)."""
	if not frappe.get_meta("Blood Donor Test").has_field("crossmatch_result"):
		return {}
	rows = frappe.get_all("Blood Donor Test", filters={"crossmatch_patient": patient, "docstatus": 1,
		"crossmatch_result": ["in", ["Compatible", "Incompatible"]]},
		fields=["name", "crossmatch_result", "crossmatch_lab_value", "lab_reference"])
	return {r.name: r for r in rows}


def request_donations(req_name):
	"""Blood Donations given for this request (by a replacement or directed donor)."""
	screenings = frappe.get_all("Blood Donor Screening", filters={"blood_request": req_name, "docstatus": 1}, pluck="name")
	or_filters = {"blood_request": req_name}
	if screenings:
		or_filters["donor_screening"] = ["in", screenings]
	return frappe.get_all("Blood Donation", filters={"docstatus": 1}, or_filters=or_filters, pluck="name")


def compatible_units(req, group, component, exclude=None):
	"""Units of the component this patient can receive now, best first:
	1. held for this patient (directed) or already crossmatched compatible in the lab,
	2. same group, 3. other compatible groups; earliest expiry first inside each group.
	Units held for another patient, untested, expired or lab-incompatible are left out."""
	exclude = set(exclude or [])
	ok_groups = allowed_groups(component, group)
	if not ok_groups:
		return []
	from_donors = set(request_donations(req.name))
	lab_xm = lab_crossmatches(req.patient)
	units = frappe.get_all("Blood Unit", filters={"component": component, "test_status": ["in", USABLE_TESTS],
		"blood_group": ["in", ok_groups], "expiry_datetime": [">", now_datetime()]},
		or_filters=[["status", "=", "Available"], ["blood_request", "=", req.name]],
		fields=["name", "component", "blood_group", "status", "expiry_datetime", "donor_test", "directed_request",
			"blood_donation", "blood_request"], order_by="expiry_datetime asc")
	first, exact, other = [], [], []
	for u in units:
		if u.name in exclude or u.status not in ("Available", "Reserved"):
			continue
		if u.directed_request and u.directed_request != req.name:
			continue
		xm = lab_xm.get(u.donor_test)
		if xm and xm.crossmatch_result == "Incompatible":
			continue
		u.lab_xm = xm
		u.tags = []
		if u.directed_request == req.name:
			u.tags.append(_("Directed for this patient"))
		if xm:
			u.tags.append(_("Lab crossmatch {0}").format(xm.crossmatch_lab_value or xm.crossmatch_result))
		if u.blood_donation in from_donors and u.directed_request != req.name:
			u.tags.append(_("From this request's donor"))
		if u.status == "Reserved":
			u.tags.append(_("Already reserved for this request"))
		(first if (xm or u.directed_request == req.name) else exact if u.blood_group == group else other).append(u)
	return first + exact + other


# ------------------------------------------------------------------ crossmatch panel
def needs_rows(req, group):
	rows = []
	for r in req.items:
		xm = needs_crossmatch(r.component)
		left = max(cint(r.units_required) - cint(r.units_reserved) - cint(r.units_issued), 0)
		stock = compatible_units(req, group, r.component) if group else []
		rows.append({"component": r.component, "required": cint(r.units_required), "reserved": cint(r.units_reserved),
			"issued": cint(r.units_issued), "left": left, "crossmatch": xm,
			"in_stock": len([u for u in stock if u.status == "Available"]),
			"groups": allowed_groups(r.component, group) if group else []})
	return rows


def table(head, body):
	th = "".join(f"<th>{h}</th>" for h in head)
	trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in body)
	return f'<table class="table table-bordered table-sm" style="margin:6px 0">{"<tr>" + th + "</tr>"}{trs}</table>'


def box(inner):
	return f'<div class="small" style="border:1px solid var(--border-color);border-radius:6px;padding:8px 10px">{inner}</div>'


def link(dt, name):
	return f'<a href="/app/{frappe.scrub(dt).replace("_", "-")}/{name}">{escape_html(name)}</a>' if name else ""


@frappe.whitelist()
def crossmatch_panel(blood_request, patient_blood_group=None):
	req = frappe.get_doc("Blood Request", blood_request)
	req.check_permission("read")
	group = patient_group(req, patient_blood_group)
	if not group:
		return box(_("Enter the patient's blood group (from the grouping result) to see which bags fit."))
	body = []
	for r in needs_rows(req, group):
		how = _("Crossmatch here") if r["crossmatch"] else _("No crossmatch: given by compatible group at Blood Issue")
		left = f"<b>{r['left']}</b>" if r["left"] else "0"
		body.append([escape_html(r["component"]), r["required"], r["reserved"], r["issued"], left, how,
			f"{r['in_stock']} ({escape_html(', '.join(r['groups']))})"])
	html = "<b>{0}</b> {1}".format(_("Patient group:"), escape_html(group))
	html += table([_("Component"), _("Requested"), _("Reserved"), _("Issued"), _("Still needed"), _("How"),
		_("Fitting bags in stock (groups allowed)")], body)
	html += _("Only Whole Blood and Red Cells are crossmatched. Plasma (FFP) and platelets from the same donations are "
		"in stock too: they are picked at <b>Blood Issue &gt; Get Reserved Units</b>.")
	html += "<div style='margin-top:8px'><b>{0}</b></div>".format(_("Donors for this request")) + donors_table(req)
	return box(html)


# ------------------------------------------------------------------ donors of a request
def donors(req):
	"""Screenings for this request with their donation and the bags made from it."""
	screenings = frappe.get_all("Blood Donor Screening", filters={"blood_request": req.name, "docstatus": ["<", 2]},
		fields=["name", "donor", "donor_name", "donor_type", "result", "docstatus", "screening_datetime"],
		order_by="screening_datetime asc")
	donations = {d.donor_screening or d.name: d for d in frappe.get_all("Blood Donation",
		filters={"name": ["in", request_donations(req.name) or [""]]},
		fields=["name", "donor", "donor_name", "donor_screening", "blood_group", "collection_datetime", "donor_type"])}
	out = []
	seen = set()
	for s in screenings:
		d = donations.get(s.name)
		seen.add(s.name)
		out.append({"screening": s, "donation": d})
	for key, d in donations.items():  # donations linked to the request without a screening of it
		if key not in seen:
			out.append({"screening": None, "donation": d})
	for row in out:
		d = row["donation"]
		row["units"] = frappe.get_all("Blood Unit", filters={"blood_donation": d.name, "status": ["!=", "Processed"]},
			fields=["name", "component", "blood_group", "status", "directed_request", "blood_request", "reserved_for"],
			order_by="creation asc") if d else []
	return out


def unit_text(u, req):
	where = _(u.status)
	if u.status in ("Reserved", "Issued", "Transfused") and u.blood_request:
		where += " " + (_("for this patient") if u.blood_request == req.name else _("for {0}").format(link("Blood Request", u.blood_request)))
	elif u.directed_request == req.name:
		where += ", " + _("held for this patient")
	elif u.status == "Available":
		where += ", " + _("in stock")
	return f"{link('Blood Unit', u.name)} {escape_html(u.component)} ({where})"


def donors_table(req):
	rows = donors(req)
	needed = cint(req.replacement_donors_needed)
	given = len([r for r in rows if r["donation"]])
	head = _("{0} of {1} replacement / directed donors have donated.").format(given, needed) if needed else ""
	if not rows:
		return head + "<div class='text-muted'>" + _("No donor screened for this request yet.") + "</div>"
	body = []
	for r in rows:
		s, d = r["screening"], r["donation"]
		donor = escape_html((s or d).donor_name or (s or d).donor)
		if s and s.docstatus == 0:
			state = _("Screening draft")
		elif s and s.result == "Deferred":
			state = "<span style='color:var(--red-600)'>" + _("Deferred") + "</span>"
		elif d:
			state = _("Donated")
		else:
			state = _("Accepted, not bled yet")
		body.append([donor, escape_html(_((s and s.donor_type) or (d and d.donor_type) or "")), link("Blood Donor Screening", s and s.name),
			state, link("Blood Donation", d and d.name), escape_html((d and d.blood_group) or ""),
			"<br>".join(unit_text(u, req) for u in r["units"])])
	return head + table([_("Donor"), _("Type"), _("Screening"), _("Result"), _("Donation"), _("Group"), _("Bags")], body)


@frappe.whitelist()
def request_donors_panel(blood_request):
	req = frappe.get_doc("Blood Request", blood_request)
	req.check_permission("read")
	return box(donors_table(req) + "<div class='text-muted'>" + _("Replacement bags go to stock and may be given to "
		"any patient; this patient gets the best compatible bag. Directed bags are held for this patient.") + "</div>")
