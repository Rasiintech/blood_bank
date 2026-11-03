"""Billing links between Blood Request and Sales Invoice."""
import frappe
from frappe import _
from frappe.utils import cint, flt

from blood_bank.utils import setting


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
	out["inpatient_patient"] = next((df.fieldname for df in patients if chk and chk in (df.depends_on or "")
		or chk and chk in (df.mandatory_depends_on or "")), patients[0].fieldname if patients else None)
	return out


def prepare_invoice(si, patient, practitioner=None, bill_to_inpatient=None):
	"""Common settings for blood bank invoices: no POS payment (billed to the account), doctor, inpatient billing."""
	f = si_fields()
	if si.meta.has_field("patient"):
		si.patient = patient
	if practitioner and f["referring"]:
		si.set(f["referring"], practitioner)
	if bill_to_inpatient and f["inpatient_check"]:
		si.set(f["inpatient_check"], 1)
		if f["inpatient_patient"]:
			si.set(f["inpatient_patient"], bill_to_inpatient)
	if si.meta.has_field("is_pos"):
		si.is_pos = 0
	si.set("payments", [])


def save_draft(si):
	"""Save the invoice as a draft so the HIS form scripts for new invoices do not change it; if a site-specific
	mandatory field is missing, return it unsaved so staff can complete it."""
	try:
		si.insert()
	except frappe.MandatoryError:
		frappe.clear_last_message()
	return si


@frappe.whitelist()
def make_sales_invoice(blood_request):
	"""The patient's invoice for the bags not already billed on replacement donors' invoices."""
	req = frappe.get_doc("Blood Request", blood_request)
	req.check_permission("read")
	if req.docstatus != 1:
		frappe.throw(_("Submit the Blood Request first"))
	customer = frappe.db.get_value("Patient", req.patient, "customer")
	if not customer:
		frappe.throw(_("Patient {0} has no Customer linked. Open the Patient and create the Customer first.").format(req.patient))
	refresh_request_invoice(req.name)
	req.reload()

	si = frappe.new_doc("Sales Invoice")
	si.customer = customer
	if si.meta.has_field("blood_request"):
		si.blood_request = req.name
	missing = []
	for row in req.items:
		qty = cint(row.units_required) - cint(row.units_billed)
		if qty <= 0:
			continue
		item = frappe.db.get_value("Blood Component", row.component, "billing_item")
		if not item:
			missing.append(row.component)
			continue
		si.append("items", {"item_code": item, "qty": qty})
	if missing:
		frappe.throw(_("Set a Billing Item on these Blood Components first: {0}").format(", ".join(missing)))
	if not si.items:
		frappe.throw(_("All units of this request are already billed (see Units Billed; replacement donors' invoices count)."),
			title=_("Already Billed"))
	prepare_invoice(si, req.patient, req.practitioner, bill_to_inpatient=req.patient if req.inpatient_record else None)
	si.set_missing_values()
	si.calculate_taxes_and_totals()
	return save_draft(si)


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
	return frappe.get_all("Sales Invoice", filters={"blood_request": request_name, "docstatus": 1},
		fields=["name", "outstanding_amount"]) if frappe.get_meta("Sales Invoice").has_field("blood_request") else []


def refresh_request_invoice(request_name):
	"""Units billed per component from every submitted invoice of the request (patient's and replacement donors')."""
	invoices = request_invoices(request_name)
	names = [i.name for i in invoices]
	qty_by_item = {}
	if names:
		for r in frappe.get_all("Sales Invoice Item", filters={"parent": ["in", names], "parenttype": "Sales Invoice"},
				fields=["item_code", "qty"]):
			qty_by_item[r.item_code] = qty_by_item.get(r.item_code, 0) + flt(r.qty)
	req = frappe.get_doc("Blood Request", request_name)
	required = billed_total = 0
	for row in req.items:
		item = frappe.db.get_value("Blood Component", row.component, "billing_item")
		billed = min(cint(qty_by_item.get(item, 0)), cint(row.units_required)) if item else 0
		qty_by_item[item] = qty_by_item.get(item, 0) - billed if item else 0
		row.db_set("units_billed", billed, update_modified=False)
		required += cint(row.units_required)
		billed_total += billed
	if not billed_total:
		status = invoice_status(req.sales_invoice) if req.sales_invoice else None
	else:
		paid = all(flt(i.outstanding_amount) <= 0 for i in invoices)
		status = "{0} {1}/{2}, {3}".format(_("Billed"), billed_total, required, _("Paid") if paid else _("Unpaid"))
	req.db_set("invoice_status", status, update_modified=False)


def on_sales_invoice_change(doc, method=None):
	screening = doc.get("blood_donor_screening")
	if screening and frappe.db.exists("Blood Donor Screening", screening):
		current = frappe.db.get_value("Blood Donor Screening", screening, "sales_invoice")
		if doc.docstatus == 1:
			frappe.db.set_value("Blood Donor Screening", screening, "sales_invoice", doc.name, update_modified=False)
		elif doc.docstatus == 2 and current == doc.name:
			frappe.db.set_value("Blood Donor Screening", screening, "sales_invoice", None, update_modified=False)

	names = set(frappe.get_all("Blood Request", filters={"sales_invoice": doc.name, "docstatus": 1}, pluck="name"))
	linked = doc.get("blood_request")
	if linked and frappe.db.exists("Blood Request", {"name": linked, "docstatus": 1}):
		names.add(linked)
	# the patient's own invoice becomes the request's Sales Invoice; donors' invoices only count as billed units
	if linked and doc.docstatus == 1 and not screening and frappe.db.exists("Blood Request", {"name": linked, "docstatus": 1}):
		if not frappe.db.get_value("Blood Request", linked, "sales_invoice"):
			frappe.db.set_value("Blood Request", linked, "sales_invoice", doc.name, update_modified=False)
		names.add(linked)
	for name in names:
		refresh_request_invoice(name)


def on_payment_change(doc, method=None):
	for ref in doc.get("references") or []:
		if ref.reference_doctype == "Sales Invoice":
			names = set(frappe.get_all("Blood Request", filters={"sales_invoice": ref.reference_name, "docstatus": 1}, pluck="name"))
			if frappe.get_meta("Sales Invoice").has_field("blood_request"):
				linked = frappe.db.get_value("Sales Invoice", ref.reference_name, "blood_request")
				if linked:
					names.add(linked)
			for name in names:
				refresh_request_invoice(name)


def validate_payment_for_issue(req, emergency, units=None):
	"""Each bag must be billed before it leaves the bank (unless emergency): billed units per component
	(patient's invoice + replacement donors' invoices) must cover everything issued so far plus this issue."""
	if emergency or not cint(setting("require_invoice_before_issue")):
		return
	refresh_request_invoice(req.name)
	req.reload()
	issuing = {}
	for u in units or []:
		comp = frappe.db.get_value("Blood Unit", u, "component")
		issuing[comp] = issuing.get(comp, 0) + 1
	short = []
	for row in req.items:
		need = cint(row.units_issued) + issuing.get(row.component, 0)
		if need > cint(row.units_billed):
			short.append(_("{0}: {1} billed, {2} needed").format(row.component, cint(row.units_billed), need))
	if short:
		frappe.throw(_("Not billed yet for Blood Request {0}:<br>{1}<br><br>Create the Sales Invoice from the request "
			"(it bills only what is missing), or submit the replacement donors' invoices.").format(req.name, "<br>".join(short)),
			title=_("Not Billed"))
	if cint(setting("require_paid_invoice")):
		unpaid = [i.name for i in request_invoices(req.name) if flt(i.outstanding_amount) > 0]
		if unpaid:
			frappe.throw(_("Not fully paid: {0}").format(", ".join(unpaid)), title=_("Not Paid"))
