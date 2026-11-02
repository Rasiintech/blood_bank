"""Read results from the hospital's lab doctype (custom Lab Result, standard Lab Test, ...)."""
import re

import frappe
from frappe import _
from frappe.utils import flt

from blood_bank.utils import get_settings, lines, parse_blood_group

NAME_FIELDS = ["test_name", "lab_test_event", "lab_test_name", "lab_test_particulars", "test_event",
	"event", "test", "particulars", "parameter", "component", "item_name", "template", "test_template"]
VALUE_FIELDS = ["result_value", "result", "value", "test_result", "observation", "result_text"]


def norm(text):
	return re.sub(r"[^a-z0-9+\-]+", " ", str(text or "").lower()).strip()


def has_phrase(text, phrase):
	return f" {norm(phrase)} " in f" {norm(text)} "


def classify_tti(value):
	"""'Non-Reactive' / 'Reactive' / None (unreadable)."""
	if value in (None, ""):
		return None
	s = get_settings()
	for kw in lines(s.non_reactive_keywords) or ["non-reactive", "non reactive", "negative"]:
		if has_phrase(value, kw):
			return "Non-Reactive"
	for kw in lines(s.reactive_keywords) or ["reactive", "positive"]:
		if has_phrase(value, kw):
			return "Reactive"
	return None


def classify_crossmatch(value):
	if value in (None, ""):
		return None
	s = get_settings()
	for kw in lines(s.incompatible_keywords) or ["incompatible"]:
		if has_phrase(value, kw):
			return "Incompatible"
	for kw in lines(s.compatible_keywords) or ["compatible"]:
		if has_phrase(value, kw):
			return "Compatible"
	return None


def parse_number(value):
	m = re.search(r"\d+(\.\d+)?", str(value or ""))
	return flt(m.group(0)) if m else None


def _pick(meta, configured, candidates):
	if configured and meta.has_field(configured):
		return configured
	for c in candidates:
		if meta.has_field(c):
			return c
	return None


def get_lab_rows(doctype, name):
	"""Return [(test_name, value)] from every result table of a lab document."""
	if not (doctype and name):
		return []
	if not frappe.has_permission(doctype, "read", name) and not frappe.has_permission("Blood Donor Test", "write"):
		frappe.throw(_("Not permitted to read {0} {1}").format(doctype, name))
	doc = frappe.get_doc(doctype, name)
	s = get_settings()
	meta = frappe.get_meta(doctype)
	table_fields = [df for df in meta.get_table_fields()]
	if s.lab_results_table and s.lab_doctype == doctype:
		table_fields = [df for df in table_fields if df.fieldname == s.lab_results_table] or table_fields

	rows = []
	for tdf in table_fields:
		cmeta = frappe.get_meta(tdf.options)
		same = s.lab_doctype == doctype
		name_f = _pick(cmeta, s.lab_test_name_field if same else None, NAME_FIELDS)
		value_f = _pick(cmeta, s.lab_result_value_field if same else None, VALUE_FIELDS)
		if not (name_f and value_f):
			continue
		for row in doc.get(tdf.fieldname) or []:
			label = row.get(name_f)
			# Standard Lab Test keeps grouped tests in lab_test_event
			if name_f == "lab_test_event" and not label:
				label = row.get("lab_test_name")
			if label:
				rows.append((str(label), row.get(value_f)))
	return rows


def find_value(rows, labels):
	wanted = {norm(l) for l in labels}
	for label, value in rows:
		if norm(label) in wanted and value not in (None, ""):
			return value
	return None


def fill_donor_test(test_doc):
	"""Copy results from the linked lab document into a Blood Donor Test. Returns a summary."""
	rows = get_lab_rows(test_doc.lab_doctype, test_doc.lab_reference)
	if not rows:
		frappe.throw(_("No result lines found in {0} {1}. Check the Lab Integration settings.")
			.format(test_doc.lab_doctype, test_doc.lab_reference))
	s = get_settings()
	filled, unread = [], []

	group_value = find_value(rows, lines(s.blood_group_labels) or ["BLOOD GROUPING"])
	if group_value:
		group = parse_blood_group(group_value)
		if group:
			test_doc.blood_group = group
			filled.append(_("Blood group: {0}").format(group))
		else:
			unread.append(_("Blood group '{0}'").format(group_value))

	hb_value = find_value(rows, lines(s.hb_labels) or ["HB"])
	if hb_value:
		hb = parse_number(hb_value)
		if hb:
			test_doc.hb_g_dl = hb
			filled.append(_("Hb: {0}").format(hb))

	for item in test_doc.tests:
		labels = lines(frappe.db.get_value("Blood Screening Test", item.screening_test, "lab_labels")) or [item.screening_test]
		value = find_value(rows, labels)
		if value is None:
			continue
		item.lab_value = str(value)[:140]
		result = classify_tti(value)
		if result:
			item.result = result
			filled.append(f"{item.screening_test}: {result}")
		else:
			unread.append(f"{item.screening_test} '{value}'")
	return {"filled": filled, "unread": unread}


def on_lab_document_submit(doc, method=None):
	"""doc_events['*'].on_submit: when the configured lab doctype is submitted, fill linked drafts."""
	if doc.doctype.startswith("Blood "):
		return
	try:
		lab_dt = get_settings().lab_doctype
	except Exception:
		return
	if doc.doctype not in (lab_dt, "Lab Test"):
		return
	screening = screening_for_lab_document(doc)
	if screening and not frappe.db.exists("Blood Donor Test", {"donor_screening": screening, "docstatus": ["<", 2]}):
		try:
			scr = frappe.db.get_value("Blood Donor Screening", screening, ["donor", "docstatus", "result"], as_dict=True)
			if scr and scr.docstatus == 1 and scr.result == "Accepted":
				test = frappe.new_doc("Blood Donor Test")
				test.donor = scr.donor
				test.donor_screening = screening
				test.lab_doctype = doc.doctype
				test.lab_reference = doc.name
				test.load_tests()
				test.flags.ignore_permissions = True
				test.insert()
		except Exception:
			frappe.log_error(title=f"Blood Bank: could not create Donor Test from {doc.doctype} {doc.name}")
	for name in frappe.get_all("Blood Donor Test", filters={"docstatus": 0, "lab_doctype": doc.doctype,
			"lab_reference": doc.name}, pluck="name"):
		test = frappe.get_doc("Blood Donor Test", name)
		try:
			fill_donor_test(test)
			test.flags.ignore_permissions = True
			test.save()
		except Exception:
			frappe.log_error(title=f"Blood Bank: could not read {doc.doctype} {doc.name}")
	for name in frappe.get_all("Blood Crossmatch", filters={"docstatus": 0, "lab_doctype": doc.doctype,
			"lab_reference": doc.name}, pluck="name"):
		xm = frappe.get_doc("Blood Crossmatch", name)
		fill_crossmatch(xm)
		xm.flags.ignore_permissions = True
		xm.save()


def fill_crossmatch(xm_doc):
	rows = get_lab_rows(xm_doc.lab_doctype, xm_doc.lab_reference)
	s = get_settings()
	value = find_value(rows, lines(s.crossmatch_labels) or ["Cross Matching"])
	result = classify_crossmatch(value)
	empty = [i for i in xm_doc.items if not i.result]
	if result and len(empty) == 1:
		empty[0].result = result
		empty[0].remarks = f"From lab: {value}"[:140]
	return result


def screening_for_lab_document(doc):
	"""The Blood Donor Screening whose tests this lab document holds, found through its Sales Invoice."""
	si = doc.get("sales_invoice")
	if not si or not frappe.get_meta("Sales Invoice").has_field("blood_donor_screening"):
		return None
	return frappe.db.get_value("Sales Invoice", si, "blood_donor_screening")


def lab_document_for_screening(lab_doctype, screening):
	"""Exact match: the lab document made from the screening's invoice."""
	si = frappe.db.get_value("Blood Donor Screening", screening, "sales_invoice")
	if not (si and lab_doctype and frappe.get_meta(lab_doctype).has_field("sales_invoice")):
		return None
	rows = frappe.get_all(lab_doctype, filters={"sales_invoice": si, "docstatus": ["<", 2]},
		fields=["name", "docstatus"], order_by="creation desc", limit=1)
	return rows[0] if rows else None
