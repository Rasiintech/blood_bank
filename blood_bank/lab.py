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
		configured = s.lab_result_value_field if same and s.lab_result_value_field and cmeta.has_field(s.lab_result_value_field) else None
		value_fs = [configured] if configured else [f for f in VALUE_FIELDS if cmeta.has_field(f)]
		value_fs += [df.fieldname for df in cmeta.fields if df.fieldtype == "Select" and df.fieldname not in value_fs
			and "result" in (df.fieldname + " " + (df.label or "")).lower()]
		if not (name_f and value_fs):
			continue
		for row in doc.get(tdf.fieldname) or []:
			# grouped/compound rows keep the test name in lab_test_event, single tests in lab_test_name
			label = row.get(name_f)
			if name_f == "lab_test_event" and not label:
				label = row.get("lab_test_name")
			value = next((row.get(f) for f in value_fs if row.get(f) not in (None, "")), None)
			if label:
				rows.append((str(label), value))
	return rows


def find_value(rows, labels):
	wanted = {norm(l) for l in labels}
	for label, value in rows:
		if norm(label) in wanted and value not in (None, ""):
			return value
	return None


def fill_donor_test(test_doc):
	"""Copy results from the linked lab document into a Blood Donor Test. Returns a summary."""
	names = []
	if test_doc.lab_reference:
		names.append(test_doc.lab_reference)
	if test_doc.lab_doctype and test_doc.donor_screening:
		for n in lab_documents_for_screening(test_doc.lab_doctype, test_doc.donor_screening):
			if n not in names:
				names.append(n)
	rows = []
	for n in names:
		rows += get_lab_rows(test_doc.lab_doctype, n)
	if not rows:
		frappe.throw(_("No result lines found in {0} {1}. Check the Lab Integration settings.")
			.format(test_doc.lab_doctype, ", ".join(names) or "-"))
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
	if screening:
		try:
			upsert_donor_test(screening, doc)
		except Exception:
			frappe.log_error(title=f"Blood Bank: could not fill Donor Test from {doc.doctype} {doc.name}")
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


SAMPLE_FIELDS = ["sample_collection", "reff_collection"]
INVOICE_FIELDS = ["sales_invoice", "invoice_no", "reff_invoice"]


def upsert_donor_test(screening, doc):
	"""Create the screening's draft Donor Test from a submitted lab document, or refill the existing draft."""
	scr = frappe.db.get_value("Blood Donor Screening", screening, ["donor", "docstatus", "result"], as_dict=True)
	existing = frappe.db.get_value("Blood Donor Test", {"donor_screening": screening, "docstatus": ["<", 2]}, ["name", "docstatus"], as_dict=True)
	if existing and existing.docstatus == 0:
		test = frappe.get_doc("Blood Donor Test", existing.name)
		test.lab_doctype = test.lab_doctype or doc.doctype
		test.lab_reference = test.lab_reference or doc.name
		fill_donor_test(test)
		test.flags.ignore_permissions = True
		test.save()
		return test.name
	if existing:
		return existing.name
	if scr and scr.docstatus == 1 and scr.result == "Accepted":
		test = frappe.new_doc("Blood Donor Test")
		test.donor = scr.donor
		test.donor_screening = screening
		test.lab_doctype = doc.doctype
		test.lab_reference = doc.name
		test.load_tests()
		fill_donor_test(test)
		test.flags.ignore_permissions = True
		test.insert()
		return test.name


def lab_documents_status(lab_doctype, screening):
	"""All lab documents of the screening's sample / invoice, with their docstatus."""
	if not lab_doctype or not frappe.db.exists("DocType", lab_doctype):
		return []
	meta = frappe.get_meta(lab_doctype)
	sc, si = frappe.db.get_value("Blood Donor Screening", screening, ["sample_collection", "sales_invoice"])
	pairs = [(f, sc) for f in _ref_fields(meta, SAMPLE_FIELDS, "Sample Collection")]
	pairs += [(f, si) for f in _ref_fields(meta, INVOICE_FIELDS, "Sales Invoice")]
	seen, out = set(), []
	for field, value in pairs:
		if not value:
			continue
		for r in frappe.get_all(lab_doctype, filters={field: value, "docstatus": ["<", 2]}, fields=["name", "docstatus"], order_by="creation asc"):
			if r.name not in seen:
				seen.add(r.name)
				out.append(r)
	return out


def _ref_fields(meta, names, target):
	"""Fields of a lab doctype that point to a Sample Collection / Sales Invoice (Link or Data)."""
	found = [n for n in names if meta.has_field(n)]
	for df in meta.fields:
		if df.fieldtype == "Link" and df.options == target and df.fieldname not in found:
			found.append(df.fieldname)
	return found


def screening_for_lab_document(doc):
	"""The Blood Donor Screening whose tests this lab document holds: via its Sample Collection or Sales Invoice."""
	meta = frappe.get_meta(doc.doctype)
	for f in _ref_fields(meta, SAMPLE_FIELDS, "Sample Collection"):
		sc = doc.get(f)
		if not sc or not frappe.db.exists("Sample Collection", sc):
			continue
		if frappe.get_meta("Sample Collection").has_field("blood_donor_screening"):
			name = frappe.db.get_value("Sample Collection", sc, "blood_donor_screening")
			if name:
				return name
		name = frappe.db.get_value("Blood Donor Screening", {"sample_collection": sc}, "name")
		if name:
			return name
		scm = frappe.get_meta("Sample Collection")
		for inv_f in [f for f in ("reff_invoice", "sales_invoice") if scm.has_field(f)]:
			si = frappe.db.get_value("Sample Collection", sc, inv_f)
			if si and frappe.get_meta("Sales Invoice").has_field("blood_donor_screening"):
				name = frappe.db.get_value("Sales Invoice", si, "blood_donor_screening")
				if name:
					return name
	if frappe.get_meta("Sales Invoice").has_field("blood_donor_screening"):
		for f in _ref_fields(meta, INVOICE_FIELDS, "Sales Invoice"):
			si = doc.get(f)
			if si and frappe.db.exists("Sales Invoice", si):
				name = frappe.db.get_value("Sales Invoice", si, "blood_donor_screening")
				if name:
					return name
	return None


def lab_documents_for_screening(lab_doctype, screening, submitted_only=True):
	"""All lab documents made from the screening's Sample Collection or invoice."""
	meta = frappe.get_meta(lab_doctype)
	sc, si = frappe.db.get_value("Blood Donor Screening", screening, ["sample_collection", "sales_invoice"]) or (None, None)
	pairs = [(f, sc) for f in _ref_fields(meta, SAMPLE_FIELDS, "Sample Collection")]
	pairs += [(f, si) for f in _ref_fields(meta, INVOICE_FIELDS, "Sales Invoice")]
	names = []
	for field, value in pairs:
		if value:
			flt = {field: value, "docstatus": 1 if submitted_only else ["<", 2]}
			for n in frappe.get_all(lab_doctype, filters=flt, pluck="name"):
				if n not in names:
					names.append(n)
	# invoice-made samples: HIS links the Lab Result to the Sample Collection made from the invoice
	if si and frappe.db.exists("DocType", "Sample Collection"):
		scm = frappe.get_meta("Sample Collection")
		for inv_f in [f for f in ("reff_invoice", "sales_invoice") if scm.has_field(f)]:
			for sc2 in frappe.get_all("Sample Collection", filters={inv_f: si, "docstatus": ["<", 2]}, pluck="name"):
				for f in _ref_fields(meta, SAMPLE_FIELDS, "Sample Collection"):
					flt = {f: sc2, "docstatus": 1 if submitted_only else ["<", 2]}
					for n in frappe.get_all(lab_doctype, filters=flt, pluck="name"):
						if n not in names:
							names.append(n)
	return names


def lab_document_for_screening(lab_doctype, screening):
	"""Exact match: the lab document made from the screening's Sample Collection or invoice."""
	if not lab_doctype:
		return None
	meta = frappe.get_meta(lab_doctype)
	sc, si = frappe.db.get_value("Blood Donor Screening", screening, ["sample_collection", "sales_invoice"])
	pairs = [(f, sc) for f in _ref_fields(meta, SAMPLE_FIELDS, "Sample Collection")]
	pairs += [(f, si) for f in _ref_fields(meta, INVOICE_FIELDS, "Sales Invoice")]
	for field, value in pairs:
		if value:
			rows = frappe.get_all(lab_doctype, filters={field: value, "docstatus": ["<", 2]},
				fields=["name", "docstatus"], order_by="creation desc", limit=1)
			if rows:
				return rows[0]
	return None
