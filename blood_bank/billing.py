"""Patient billing for the blood bank.

One rule: the patient is charged for what the blood bank did for them, once.

  Blood Unit       one per bag issued (the component's Billing Item)
  Crossmatch       one per crossmatch done (setting: or included in the bag price)
  Blood Grouping   once per request (setting)
  Non-Replacement  per missing replacement donor, after the grace days (setting)

Billing Mode, chosen when the request is submitted (inpatients and outpatients can differ):
  On Issue    charges follow what happened: crossmatch, issue; a bag returned in time is credited
  On Request  the requested bags (and their crossmatches) are invoiced up front; what was not used is credited
              when the request closes

How: `reconcile(request)` works out what should be charged now from the request's documents, compares it with
the charges already posted (the request's Blood Bank Charges table) and posts only the difference: a new unpaid
invoice for anything missing, a credit note for anything charged too much. Every event calls it, so a charge can
never be posted twice and nothing is lost if one step fails; the officer can run it again with Update Charges.
"""
import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime, nowdate

from blood_bank.utils import OFFICER, has_role, setting

CLOSED = ("Completed", "Closed", "Cancelled")
UNIT, XM, GROUP, NRF = "Blood Unit", "Crossmatch", "Blood Grouping", "Non-Replacement Fee"
TYPE_ORDER = {GROUP: 0, XM: 1, UNIT: 2, NRF: 3}


# ------------------------------------------------------------------ site-specific invoice fields
def si_fields():
	"""Sales Invoice fields that differ between sites (Healthcare / HIS custom fields), found by type and label."""
	meta = frappe.get_meta("Sales Invoice")
	out = {"referring": None, "inpatient_check": None, "inpatient_patient": None}
	if meta.has_field("ref_practitioner"):
		out["referring"] = "ref_practitioner"
	else:
		out["referring"] = next((df.fieldname for df in meta.fields if df.fieldtype == "Link"
			and df.options == "Healthcare Practitioner"), None)
	out["inpatient_check"] = next((df.fieldname for df in meta.fields if df.fieldtype == "Check"
		and "inpatient" in (df.label or "").lower().replace(" ", "").replace("-", "")), None)
	patients = [df for df in meta.fields if df.fieldtype == "Link" and df.options == "Patient" and df.fieldname != "patient"]
	chk = out["inpatient_check"]
	out["inpatient_patient"] = next((df.fieldname for df in patients if chk and (chk in (df.depends_on or "")
		or chk in (df.mandatory_depends_on or ""))), patients[0].fieldname if patients else None)
	return out


ADMITTED = ("Admitted", "Admission Scheduled", "Discharge Scheduled")


def current_admission(patient):
	"""The patient's open Inpatient Record, if any (the request may have been made without picking it)."""
	if not patient or not frappe.db.exists("DocType", "Inpatient Record"):
		return None
	return frappe.db.get_value("Inpatient Record", {"patient": patient, "status": ["in", ADMITTED]}, "name",
		order_by="creation desc")


def is_inpatient(req):
	record = req.get("inpatient_record") or current_admission(req.patient)
	if not record:
		return False
	return frappe.db.get_value("Inpatient Record", record, "status") in ADMITTED


def billing_mode_for(req):
	return setting("inpatient_billing" if is_inpatient(req) else "outpatient_billing") or "On Issue"


# ------------------------------------------------------------------ what should be charged
def requires_crossmatch(component):
	return cint(frappe.db.get_value("Blood Component", component, "requires_crossmatch"))


def issued_units(req_name):
	"""{component: count} of bags issued for the request and not returned to stock."""
	returned = set()
	for r in frappe.get_all("Blood Unit Return Item", filters={"parenttype": "Blood Unit Return", "outcome": "Returned to Stock"},
			fields=["parent", "blood_unit"]):
		if frappe.db.get_value("Blood Unit Return", r.parent, "docstatus") == 1:
			issue = frappe.db.get_value("Blood Unit Return", r.parent, "blood_issue")
			returned.add((issue, r.blood_unit))
	out = {}
	for issue in frappe.get_all("Blood Issue", filters={"blood_request": req_name, "docstatus": 1}, pluck="name"):
		for row in frappe.get_all("Blood Issue Item", filters={"parent": issue, "parenttype": "Blood Issue"},
				fields=["blood_unit", "component"]):
			if (issue, row.blood_unit) in returned:
				continue
			comp = row.component or frappe.db.get_value("Blood Unit", row.blood_unit, "component")
			out[comp] = out.get(comp, 0) + 1
	return out


def crossmatches_done(req_name):
	"""{component: count} of crossmatches done (any result) on submitted crossmatches of the request."""
	out = {}
	for xm in frappe.get_all("Blood Crossmatch", filters={"blood_request": req_name, "docstatus": 1}, pluck="name"):
		for row in frappe.get_all("Blood Crossmatch Item", filters={"parent": xm, "parenttype": "Blood Crossmatch"},
				fields=["component", "result", "blood_unit"]):
			if not row.result:
				continue
			comp = row.component or frappe.db.get_value("Blood Unit", row.blood_unit, "component")
			out[comp] = out.get(comp, 0) + 1
	return out


def nrf_due(req):
	"""Missing replacement donors to charge, once the grace days after closing have passed."""
	if setting("non_replacement_fee") != "Per missing donor" or cint(req.nrf_waived) or req.docstatus != 1:
		return 0
	if req.status not in ("Completed", "Closed") or not req.closed_on:
		return 0
	grace = cint(setting("non_replacement_grace_days"))
	if getdate(add_days(req.closed_on, grace)) > getdate(nowdate()):
		return 0
	donations = frappe.db.count("Blood Donation", {"blood_request": req.name, "docstatus": 1})
	return max(cint(req.replacement_donors_needed) - donations, 0)


def expected_charges(req):
	"""{(charge_type, component): qty} the patient should be charged right now."""
	out = {}
	if req.docstatus != 1 or req.status == "Cancelled":
		return out
	mode = req.billing_mode or billing_mode_for(req)
	closed = req.status in CLOSED
	issued = issued_units(req.name)
	done = crossmatches_done(req.name)
	separate_xm = setting("crossmatch_charge") != "Included in bag price"

	for row in req.items:
		comp = row.component
		units = issued.get(comp, 0)
		if mode == "On Request" and not closed:
			units = max(units, cint(row.units_required))
		if units:
			out[(UNIT, comp)] = units
		if separate_xm and requires_crossmatch(comp):
			xms = done.get(comp, 0)
			if mode == "On Request" and not closed:
				xms = max(xms, cint(row.units_required))
			if xms:
				out[(XM, comp)] = xms
	if cint(setting("charge_blood_grouping")):
		started = any(done.values()) or any(issued.values())
		if (mode == "On Request" and not closed) or started:
			out[(GROUP, None)] = 1
	missing = nrf_due(req)
	if missing:
		out[(NRF, None)] = missing
	return out


def charged_so_far(req):
	out = {}
	for c in req.get("charges") or []:
		key = (c.charge_type, c.component or None)
		out[key] = out.get(key, 0) + flt(c.qty)
	return out


DEFAULT_ITEMS = {XM: "BB-XM", GROUP: "BB-GRP", NRF: "BB-NRF"}
SETTING_ITEMS = {XM: "crossmatch_item", GROUP: "grouping_item", NRF: "non_replacement_item"}


def item_for(charge_type, component):
	if charge_type == UNIT:
		return frappe.db.get_value("Blood Component", component, "billing_item")
	item = setting(SETTING_ITEMS[charge_type]) or DEFAULT_ITEMS[charge_type]
	return item if frappe.db.exists("Item", item) else None


# ------------------------------------------------------------------ posting
@frappe.whitelist()
def update_charges(blood_request):
	"""Update Charges button on the request (officer / billing): post whatever is missing."""
	req = frappe.get_doc("Blood Request", blood_request)
	req.check_permission("read")
	return reconcile(req, reference=req, quiet=False)


def reconcile(req, reference=None, quiet=True):
	"""Post the difference between what should be charged and what was charged. Returns a summary."""
	if isinstance(req, str):
		req = frappe.get_doc("Blood Request", req)
	if req.docstatus == 0:
		return {}
	drop_void_charges(req)
	repriced = None
	try:
		reprice_drafts(req)  # $0 drafts made before prices were set
	except Exception as e:
		frappe.log_error(title=f"Blood Bank: could not update draft invoice of {req.name}")
		repriced = _("Draft invoice not updated: {0}").format(frappe.utils.strip_html(str(e))[:300])
	want = expected_charges(req)
	have = charged_so_far(req)
	add, remove = [], []
	for key in sorted(set(want) | set(have), key=lambda k: (TYPE_ORDER.get(k[0], 9), k[1] or "")):
		diff = flt(want.get(key, 0)) - flt(have.get(key, 0))
		if diff > 0:
			add.append((key[0], key[1], diff))
		elif diff < 0:
			remove.append((key[0], key[1], -diff))
	summary = {"charged": [], "credited": [], "problems": [repriced] if repriced else []}
	reference = reference or req
	# credits first, so a line that is no longer due is removed from a draft instead of being posted and credited
	if remove:
		try:
			summary["credited"] = credit(req, remove, reference)
		except Exception as e:
			frappe.log_error(title=f"Blood Bank: could not credit {req.name}")
			summary["problems"].append(_("Credit not posted: {0}").format(frappe.utils.strip_html(str(e))[:300]))
	if add:
		try:
			si = post_invoice(req, add, reference)
			summary["charged"] = [f"{t}{' ' + c if c else ''} x {q:g}" for t, c, q in add] + [si.name]
		except Exception as e:
			frappe.log_error(title=f"Blood Bank: could not charge {req.name}")
			summary["problems"].append(_("Charges not posted: {0}").format(frappe.utils.strip_html(str(e))[:300]))
	try:
		submit_drafts(req)
	except Exception as e:
		frappe.log_error(title=f"Blood Bank: could not submit invoice of {req.name}")
		summary["problems"].append(_("Invoice not submitted: {0}").format(frappe.utils.strip_html(str(e))[:300]))
	refresh_request_invoice(req.name)
	if summary["problems"] and not quiet:
		frappe.msgprint("<br>".join(summary["problems"]), title=_("Billing"), indicator="orange")
	elif summary["problems"]:
		frappe.msgprint("<br>".join(summary["problems"]) + "<br>" + _("Fix it, then use Update Charges on the request."),
			title=_("Billing"), indicator="orange")
	return summary


def drop_void_charges(req):
	"""Forget charge rows whose invoice was deleted (a draft) or cancelled by the cashier, so Update Charges posts
	them again (e.g. a draft made before the item prices were set)."""
	void = []
	for c in req.get("charges") or []:
		status = frappe.db.get_value("Sales Invoice", c.sales_invoice, "docstatus") if c.sales_invoice else 2
		if status is None or cint(status) == 2:
			void.append(c)
	if not void:
		return
	for c in void:
		frappe.db.delete("Blood Request Charge", {"name": c.name})
		req.charges.remove(c)
	if req.sales_invoice and not frappe.db.exists("Sales Invoice", {"name": req.sales_invoice, "docstatus": ["<", 2]}):
		first = next((c.sales_invoice for c in req.charges if c.sales_invoice), None)
		req.db_set("sales_invoice", first, update_modified=False)


def reprice_drafts(req):
	"""Draft invoices of the request made before the item prices were set ($0 lines): fetch the prices again."""
	for name in dict.fromkeys(c.sales_invoice for c in req.get("charges") or [] if c.sales_invoice):
		if frappe.db.get_value("Sales Invoice", name, "docstatus") != 0:
			continue
		si = frappe.get_doc("Sales Invoice", name)
		if any(flt(i.rate) == 0 for i in si.items):
			lines = [(i.item_code, i.qty) for i in si.items]
			si.set("items", [])
			for item_code, qty in lines:
				si.append("items", {"item_code": item_code, "qty": qty})
			si.set_missing_values()
			si.calculate_taxes_and_totals()
			si.flags.ignore_permissions = True
			si.save()
		rates = {i.item_code: flt(i.rate) for i in si.items}
		for c in req.charges:
			if c.sales_invoice == name and c.item_code in rates and flt(c.rate) != rates[c.item_code]:
				c.db_set({"rate": rates[c.item_code], "amount": rates[c.item_code] * flt(c.qty)}, update_modified=False)


def draft_invoices(req):
	out = []
	for n in dict.fromkeys(c.sales_invoice for c in req.get("charges") or [] if c.sales_invoice):
		v = frappe.db.get_value("Sales Invoice", n, ["docstatus", "is_return"], as_dict=True)
		if v and cint(v.docstatus) == 0 and not cint(v.is_return):
			out.append(n)
	return out


def submit_drafts(req):
	"""Submit the request's draft invoices (and draft credit notes) when Settings say so and every line has a price."""
	if not cint(setting("submit_charge_invoices")):
		return
	names = dict.fromkeys(c.sales_invoice for c in req.get("charges") or [] if c.sales_invoice)
	# invoices before their credit notes
	for name in sorted(names, key=lambda n: cint(frappe.db.get_value("Sales Invoice", n, "is_return"))):
		if frappe.db.get_value("Sales Invoice", name, "docstatus") != 0:
			continue
		si = frappe.get_doc("Sales Invoice", name)
		if any(flt(i.rate) == 0 for i in si.items):
			continue  # no price yet: leave it for the cashier
		si.flags.ignore_permissions = True
		si.submit()


def new_invoice(req):
	customer = frappe.db.get_value("Patient", req.patient, "customer")
	if not customer:
		frappe.throw(_("Patient {0} has no Customer. Open the Patient and create the Customer first.").format(req.patient))
	si = frappe.new_doc("Sales Invoice")
	si.customer = customer
	f = si_fields()
	if si.meta.has_field("patient"):
		si.patient = req.patient
	if si.meta.has_field("blood_request"):
		si.blood_request = req.name
	if req.practitioner and f["referring"]:
		si.set(f["referring"], req.practitioner)
	if is_inpatient(req) and f["inpatient_check"]:
		si.set(f["inpatient_check"], 1)
		if f["inpatient_patient"]:
			si.set(f["inpatient_patient"], req.patient)
	if si.meta.has_field("is_pos"):
		si.is_pos = 0
	si.set("payments", [])
	return si


def post_invoice(req, lines, reference):
	"""Add the lines to the request's open draft invoice, or to a new invoice. One charge row per line."""
	drafts = draft_invoices(req)
	si = frappe.get_doc("Sales Invoice", drafts[-1]) if drafts else new_invoice(req)
	start = len(si.items)
	missing = []
	for charge_type, component, qty in lines:
		item = item_for(charge_type, component)
		if not item:
			missing.append(component or charge_type)
			continue
		si.append("items", {"item_code": item, "qty": qty})
	if missing:
		frappe.throw(_("No billing item for: {0}. Set it on the Blood Component or in Blood Bank Settings > Patient Billing.")
			.format(", ".join(missing)))
	if si.is_new():
		si.remarks = _("Blood bank charges for {0} ({1} {2})").format(req.name, reference.doctype, reference.name)
	si.set_missing_values()
	si.calculate_taxes_and_totals()
	si.flags.ignore_permissions = True
	si.save()  # submitted later by submit_drafts(), after any credit in the same update
	for (charge_type, component, qty), item in zip(lines, si.items[start:]):
		add_charge_row(req, charge_type, component, qty, item.item_code, item.rate, item.amount, si.name, reference)
	if not req.sales_invoice:
		req.db_set("sales_invoice", si.name, update_modified=False)
	return si


def add_charge_row(req, charge_type, component, qty, item, rate, amount, invoice, reference):
	row = req.append("charges", {"charge_datetime": now_datetime(), "charge_type": charge_type, "component": component,
		"qty": qty, "item_code": item, "rate": rate, "amount": amount, "sales_invoice": invoice,
		"reference_doctype": reference.doctype, "reference_name": reference.name})
	row.parent, row.parenttype, row.parentfield = req.name, "Blood Request", "charges"
	row.idx = len(req.charges)
	row.db_insert()


def credit(req, lines, reference):
	"""Credit back over-charged quantities against the invoices that charged them (newest first)."""
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	done = []
	for charge_type, component, qty in lines:
		left = qty
		rows = [c for c in req.charges if c.charge_type == charge_type and (c.component or None) == component]
		# what is still creditable per invoice
		per_invoice = {}
		for c in rows:
			per_invoice[c.sales_invoice] = per_invoice.get(c.sales_invoice, 0) + flt(c.qty)
		for invoice in sorted(per_invoice, key=lambda n: n or "", reverse=True):
			avail = per_invoice[invoice]
			if left <= 0 or avail <= 0:
				continue
			take = min(avail, left)
			item = next(c.item_code for c in rows if c.sales_invoice == invoice)
			status = frappe.db.get_value("Sales Invoice", invoice, "docstatus")
			if status == 0:
				# still a draft: simply lower the quantity on it
				si = frappe.get_doc("Sales Invoice", invoice)
				for it in si.items:
					if it.item_code == item and take > 0:
						cut = min(flt(it.qty), take)
						it.qty = flt(it.qty) - cut
				si.items = [it for it in si.items if flt(it.qty) > 0]
				if si.items:
					si.calculate_taxes_and_totals(); si.flags.ignore_permissions = True; si.save()
				else:
					if req.sales_invoice == invoice:
						req.db_set("sales_invoice", None, update_modified=False)
					frappe.delete_doc("Sales Invoice", invoice, ignore_permissions=True, force=True)
				rate = next((c.rate for c in rows if c.sales_invoice == invoice), 0)
				add_charge_row(req, charge_type, component, -take, item, rate, -take * flt(rate), invoice, reference)
				done.append(f"{charge_type} x {take:g} ({invoice})")
			elif status == 1:
				ret = make_return_doc("Sales Invoice", invoice)
				ret.items = [it for it in ret.items if it.item_code == item][:1]
				if not ret.items:
					continue
				ret.items[0].qty = -take
				ret.remarks = _("Blood bank credit for {0} ({1} {2})").format(req.name, reference.doctype, reference.name)
				ret.calculate_taxes_and_totals()
				ret.flags.ignore_permissions = True
				ret.insert()
				if cint(setting("submit_charge_invoices")):
					ret.submit()
				add_charge_row(req, charge_type, component, -take, item, ret.items[0].rate, ret.items[0].amount, ret.name, reference)
				done.append(f"{charge_type} x {take:g} ({ret.name})")
			left -= take
	return done


# ------------------------------------------------------------------ status shown on the request
def invoice_status(si_name):
	if not si_name:
		return None
	si = frappe.db.get_value("Sales Invoice", si_name, ["docstatus", "outstanding_amount", "status"], as_dict=True)
	if not si:
		return None
	if si.docstatus == 0:
		return "Draft"
	if si.docstatus == 2:
		return "Cancelled"
	return "Paid" if flt(si.outstanding_amount) <= 0 else "Unpaid"


def request_invoices(request_name):
	names = frappe.get_all("Blood Request Charge", filters={"parent": request_name, "parenttype": "Blood Request"},
		pluck="sales_invoice")
	return frappe.get_all("Sales Invoice", filters={"name": ["in", list(set(n for n in names if n))] or [""]},
		fields=["name", "docstatus", "outstanding_amount", "grand_total", "is_return"])


def refresh_request_invoice(request_name):
	"""Units Billed per row, Total Charged and Billing Status from the charges table."""
	rows = frappe.get_all("Blood Request Charge", filters={"parent": request_name, "parenttype": "Blood Request"},
		fields=["charge_type", "component", "qty", "amount"])
	by_comp = {}
	for r in rows:
		if r.charge_type == UNIT:
			by_comp[r.component] = by_comp.get(r.component, 0) + flt(r.qty)
	for item in frappe.get_all("Blood Request Item", filters={"parent": request_name, "parenttype": "Blood Request"},
			fields=["name", "component"]):
		frappe.db.set_value("Blood Request Item", item.name, "units_billed", cint(by_comp.get(item.component, 0)), update_modified=False)
	total = sum(flt(r.amount) for r in rows)
	invoices = request_invoices(request_name)
	if not rows:
		status = None
	elif any(i.docstatus == 0 for i in invoices):
		status = "Draft invoice"
	else:
		due = sum(flt(i.outstanding_amount) for i in invoices if i.docstatus == 1)
		status = "Unpaid" if due > 0.005 else "Refund due" if due < -0.005 else "Paid"
	frappe.db.set_value("Blood Request", request_name, {"total_charged": total, "invoice_status": status}, update_modified=False)


def on_sales_invoice_change(doc, method=None):
	"""An invoice of a request changed (paid, cancelled): refresh the request's billing status."""
	screening = doc.get("blood_donor_screening")
	if screening and frappe.db.exists("Blood Donor Screening", screening):
		current = frappe.db.get_value("Blood Donor Screening", screening, "sales_invoice")
		if doc.docstatus == 1:
			frappe.db.set_value("Blood Donor Screening", screening, "sales_invoice", doc.name, update_modified=False)
		elif doc.docstatus == 2 and current == doc.name:
			frappe.db.set_value("Blood Donor Screening", screening, "sales_invoice", None, update_modified=False)
	names = set(frappe.get_all("Blood Request Charge", filters={"sales_invoice": doc.name, "parenttype": "Blood Request"}, pluck="parent"))
	if doc.get("return_against"):
		names |= set(frappe.get_all("Blood Request Charge", filters={"sales_invoice": doc.return_against, "parenttype": "Blood Request"}, pluck="parent"))
	if doc.docstatus == 2:
		# a cancelled invoice no longer charges anything: drop its rows so Update Charges posts them again
		for name in names:
			frappe.db.delete("Blood Request Charge", {"parent": name, "sales_invoice": doc.name})
	for name in names:
		refresh_request_invoice(name)


def on_payment_change(doc, method=None):
	for ref in doc.get("references") or []:
		if ref.reference_doctype == "Sales Invoice":
			for name in set(frappe.get_all("Blood Request Charge", filters={"sales_invoice": ref.reference_name,
					"parenttype": "Blood Request"}, pluck="parent")):
				refresh_request_invoice(name)


# ------------------------------------------------------------------ issue gate (On Request)
def validate_payment_for_issue(req, emergency, units=None):
	"""On Request: the bags must be on a submitted (and, if set, paid) invoice before they leave the bank."""
	if emergency or (req.billing_mode or billing_mode_for(req)) != "On Request":
		return
	if not cint(setting("require_invoice_before_issue")):
		return
	issued = issued_units(req.name)
	issuing = {}
	for u in units or []:
		comp = frappe.db.get_value("Blood Unit", u, "component")
		issuing[comp] = issuing.get(comp, 0) + 1
	paid_for = {}
	for c in req.get("charges") or []:
		if c.charge_type == UNIT and frappe.db.get_value("Sales Invoice", c.sales_invoice, "docstatus") == 1:
			paid_for[c.component] = paid_for.get(c.component, 0) + flt(c.qty)
	short = [_("{0}: {1} invoiced, {2} needed").format(comp, cint(paid_for.get(comp, 0)), issued.get(comp, 0) + n)
		for comp, n in issuing.items() if issued.get(comp, 0) + n > paid_for.get(comp, 0)]
	if short:
		frappe.throw(_("Billing mode On Request: these bags are not on a submitted invoice yet:<br>{0}<br><br>"
			"Submit the request's invoice (or use Update Charges), then issue.").format("<br>".join(short)), title=_("Not Billed"))
	if cint(setting("require_paid_invoice")):
		unpaid = [i.name for i in request_invoices(req.name) if i.docstatus == 1 and not i.is_return and flt(i.outstanding_amount) > 0]
		if unpaid:
			frappe.throw(_("Not paid yet: {0}").format(", ".join(unpaid)), title=_("Not Paid"))


# ------------------------------------------------------------------ closing a request
@frappe.whitelist()
def close_request(blood_request, reason):
	"""The patient no longer needs blood: no more crossmatch or issue; On Request credits what was not used."""
	req = frappe.get_doc("Blood Request", blood_request)
	if not (has_role(OFFICER) or "Physician" in frappe.get_roles()):
		frappe.throw(_("Only a Blood Bank Officer or doctor can close a request"), frappe.PermissionError)
	if req.docstatus != 1 or req.status in CLOSED:
		frappe.throw(_("Request {0} is {1}").format(req.name, req.status))
	if not (reason or "").strip():
		frappe.throw(_("Give the reason (e.g. surgery done, patient discharged)"))
	from blood_bank.utils import update_unit
	for name in frappe.get_all("Blood Unit", filters={"blood_request": req.name, "status": "Reserved"}, pluck="name"):
		update_unit(name, status="Available", reserved_for=None, blood_request=None, crossmatch=None, reserved_until=None)
	req.db_set({"status": "Closed", "closed_on": now_datetime(), "close_reason": reason.strip()}, update_modified=False)
	req.reload()
	reconcile(req, reference=req)
	return req.status


@frappe.whitelist()
def waive_non_replacement_fee(blood_request, reason):
	if not has_role(OFFICER):
		frappe.throw(_("Only a Blood Bank Officer can waive the fee"), frappe.PermissionError)
	if not (reason or "").strip():
		frappe.throw(_("Give the reason"))
	req = frappe.get_doc("Blood Request", blood_request)
	req.db_set({"nrf_waived": 1, "nrf_waive_reason": reason.strip()}, update_modified=False)
	req.reload()
	reconcile(req, reference=req)


def daily_billing():
	"""Daily: close requests of discharged patients and charge Non-Replacement Fees whose grace days ended."""
	for r in frappe.get_all("Blood Request", filters={"docstatus": 1, "status": ["not in", CLOSED], "inpatient_record": ["is", "set"]},
			fields=["name", "inpatient_record"]):
		if frappe.db.get_value("Inpatient Record", r.inpatient_record, "status") == "Discharged":
			try:
				req = frappe.get_doc("Blood Request", r.name)
				from blood_bank.utils import update_unit
				for name in frappe.get_all("Blood Unit", filters={"blood_request": r.name, "status": "Reserved"}, pluck="name"):
					update_unit(name, status="Available", reserved_for=None, blood_request=None, crossmatch=None, reserved_until=None)
				req.db_set({"status": "Closed", "closed_on": now_datetime(), "close_reason": "Patient discharged"}, update_modified=False)
				reconcile(frappe.get_doc("Blood Request", r.name))
			except Exception:
				frappe.log_error(title=f"Blood Bank: could not close {r.name}")
	if setting("non_replacement_fee") == "Per missing donor":
		for name in frappe.get_all("Blood Request", filters={"docstatus": 1, "status": ["in", ["Completed", "Closed"]],
				"nrf_waived": 0, "closed_on": ["is", "set"]}, pluck="name"):
			req = frappe.get_doc("Blood Request", name)
			if nrf_due(req) > flt(charged_so_far(req).get((NRF, None), 0)):
				reconcile(req)
	frappe.db.commit()
