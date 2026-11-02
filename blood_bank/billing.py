"""Billing links between Blood Request and Sales Invoice."""
import frappe
from frappe import _
from frappe.utils import cint, flt

from blood_bank.utils import setting


@frappe.whitelist()
def make_sales_invoice(blood_request):
	req = frappe.get_doc("Blood Request", blood_request)
	req.check_permission("read")
	if req.docstatus != 1:
		frappe.throw(_("Submit the Blood Request first"))
	customer = frappe.db.get_value("Patient", req.patient, "customer")
	if not customer:
		frappe.throw(_("Patient {0} has no Customer linked. Open the Patient and create the Customer first.").format(req.patient))

	si = frappe.new_doc("Sales Invoice")
	si.customer = customer
	if si.meta.has_field("patient"):
		si.patient = req.patient
	if si.meta.has_field("blood_request"):
		si.blood_request = req.name
	missing = []
	for row in req.items:
		item = frappe.db.get_value("Blood Component", row.component, "billing_item")
		if not item:
			missing.append(row.component)
			continue
		si.append("items", {"item_code": item, "qty": cint(row.units_required) or 1})
	if missing:
		frappe.throw(_("Set a Billing Item on these Blood Components first: {0}").format(", ".join(missing)))
	si.set_missing_values()
	si.calculate_taxes_and_totals()
	return si


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


def refresh_request_invoice(request_name):
	si = frappe.db.get_value("Blood Request", request_name, "sales_invoice")
	frappe.db.set_value("Blood Request", request_name, "invoice_status", invoice_status(si), update_modified=False)


def on_sales_invoice_change(doc, method=None):
	names = set(frappe.get_all("Blood Request", filters={"sales_invoice": doc.name, "docstatus": 1}, pluck="name"))
	linked = doc.get("blood_request")
	if linked and doc.docstatus == 1 and frappe.db.exists("Blood Request", {"name": linked, "docstatus": 1}):
		if not frappe.db.get_value("Blood Request", linked, "sales_invoice"):
			frappe.db.set_value("Blood Request", linked, "sales_invoice", doc.name, update_modified=False)
		names.add(linked)
	for name in names:
		refresh_request_invoice(name)


def on_payment_change(doc, method=None):
	for ref in doc.get("references") or []:
		if ref.reference_doctype == "Sales Invoice":
			for name in frappe.get_all("Blood Request", filters={"sales_invoice": ref.reference_name, "docstatus": 1}, pluck="name"):
				refresh_request_invoice(name)


def validate_payment_for_issue(req, emergency):
	"""Patient must be billed before blood leaves the bank (unless emergency)."""
	if emergency or not cint(setting("require_invoice_before_issue")):
		return
	status = invoice_status(req.sales_invoice)
	if status not in ("Paid", "Unpaid"):
		frappe.throw(_("Blood Request {0} has no submitted Sales Invoice. Bill the patient before issuing blood.").format(req.name),
			title=_("Not Billed"))
	if cint(setting("require_paid_invoice")) and status != "Paid":
		frappe.throw(_("Sales Invoice {0} is not fully paid.").format(req.sales_invoice), title=_("Not Paid"))
