"""Bridge to the Cibaar HIS app's Sample Collection handlers, without changing HIS code.

HIS creates Lab Results on Sample Collection submit from the sample's Sales Invoice (reff_invoice) or
Hajj Screening. A free blood donor sample has neither, so for those samples only we:
  - create the Lab Results the way HIS does, from the sample's own lab test rows
  - skip the commission handlers (no invoice, nothing to commission)
Every other Sample Collection goes to the original HIS functions unchanged.

How: our before_submit / before_cancel hook on Sample Collection always runs before any on_submit /
on_cancel handler, and wraps the HIS functions in memory for this process (once). Frappe looks handlers
up by dotted path at call time, so it finds the wrapper. If HIS is not installed this does nothing.
"""
import frappe

WRAPPED_FLAG = "_blood_bank_wrapped"


def is_free_donor_sample(doc):
	return bool(doc.get("blood_donor_screening")) and not doc.get("reff_invoice") and not doc.get("hajj_screening")


def apply(doc=None, method=None):
	"""doc_events hook (Sample Collection before_submit / before_cancel). Never blocks a submit."""
	try:
		_apply()
	except Exception:
		frappe.log_error(title="Blood Bank: HIS bridge could not be applied")


def _apply():
	try:
		import his.api.create_lab_test as clt
	except ImportError:
		return
	if getattr(clt, WRAPPED_FLAG, False) or not hasattr(clt, "create_lab_tests"):
		return

	original_create = clt.create_lab_tests

	def create_lab_tests(doc, method=None):
		if is_free_donor_sample(doc):
			return create_donor_lab_results(doc)
		return original_create(doc, method)

	clt.create_lab_tests = frappe.whitelist()(create_lab_tests)

	original_cancel = getattr(clt, "on_cancel_samples", None)
	if original_cancel:
		def on_cancel_samples(doc, method=None):
			if is_free_donor_sample(doc):
				try:
					return original_cancel(doc, method)
				except Exception:
					return cancel_donor_lab_results(doc)
			return original_cancel(doc, method)

		clt.on_cancel_samples = on_cancel_samples

	try:
		import his.commission.work_handlers as wh
		for name in ("on_submit_sample_collection", "on_cancel_sample_collection"):
			original = getattr(wh, name, None)
			if original and not getattr(original, WRAPPED_FLAG, False):
				wh.__dict__[name] = _skip_for_donor(original)
	except ImportError:
		pass

	setattr(clt, WRAPPED_FLAG, True)


def _skip_for_donor(fn):
	def wrapper(doc, method=None):
		if is_free_donor_sample(doc):
			return None
		return fn(doc, method)

	setattr(wrapper, WRAPPED_FLAG, True)
	return wrapper


def _base(doc, meta):
	values = {
		"patient": doc.patient,
		"practitioner": doc.get("practitioner"),
		"lab_ref": doc.get("lab_ref"),
		"sample_details": doc.get("sample_details"),
		"reff_collection": doc.name,
	}
	out = {"doctype": "Lab Result"}
	out.update({k: v for k, v in values.items() if meta.has_field(k)})
	return out


def create_donor_lab_results(doc):
	"""Same Lab Result structure HIS builds from an invoice, but from the sample's lab test rows."""
	from blood_bank.blood_bank.doctype.blood_donor_screening.blood_donor_screening import _lab_test_table

	meta = frappe.get_meta("Lab Result")
	table, link = _lab_test_table(frappe.get_meta("Sample Collection"))
	singles = []
	for row in doc.get(table) or []:
		if not row.get(link):
			continue
		template = frappe.get_doc("Lab Test Template", row.get(link))
		if not template.department:
			continue
		if template.lab_test_template_type == "Single":
			singles.append({
				"test": template.lab_test_name,
				"lab_test_name": template.lab_test_name,
				"lab_test_uom": template.lab_test_uom,
				"secondary_uom": template.secondary_uom,
				"conversion_factor": template.conversion_factor,
				"normal_range": template.lab_test_normal_range,
				"require_result_value": 1,
				"allow_blank": 0,
			})
		elif template.lab_test_template_type == "Compound":
			items = [{
				"lab_test_event": t.lab_test_event,
				"lab_test_uom": t.lab_test_uom,
				"secondary_uom": t.secondary_uom,
				"conversion_factor": t.conversion_factor,
				"normal_range": t.normal_range,
				"require_result_value": 1,
				"allow_blank": t.allow_blank,
				"template": template.name,
			} for t in template.normal_test_templates]
			_insert(meta, doc, items, template=template.name, type_="Group")
		elif template.lab_test_template_type == "Grouped":
			items = []
			for g in template.lab_test_groups:
				if not g.lab_test_template:
					continue
				child = frappe.get_doc("Lab Test Template", g.lab_test_template)
				if child.lab_test_template_type == "Single":
					items.append({
						"lab_test_name": child.lab_test_name,
						"lab_test_uom": child.lab_test_uom,
						"secondary_uom": child.secondary_uom,
						"conversion_factor": child.conversion_factor,
						"normal_range": child.lab_test_normal_range,
						"require_result_value": 1,
						"allow_blank": 0,
						"template": child.name,
					})
				elif child.lab_test_template_type == "Compound":
					items.append({"test": template.name, "lab_test_name": child.lab_test_name or child.name, "template": template.name})
					for t in child.normal_test_templates:
						items.append({
							"lab_test_event": t.lab_test_event,
							"lab_test_uom": t.lab_test_uom,
							"secondary_uom": t.secondary_uom,
							"conversion_factor": t.conversion_factor,
							"normal_range": t.normal_range,
							"require_result_value": 1,
							"allow_blank": t.allow_blank,
							"template": child.name,
						})
			_insert(meta, doc, items, template=template.name, type_="Group")
	if singles:
		_insert(meta, doc, singles, type_="Blood")


def _insert(meta, doc, items, template=None, type_=None):
	values = _base(doc, meta)
	if meta.has_field("normal_test_items"):
		values["normal_test_items"] = items
	if template and meta.has_field("template"):
		values["template"] = template
	if template and meta.has_field("lab_test_name"):
		values["lab_test_name"] = template
	if type_ and meta.has_field("type"):
		values["type"] = type_
	lr = frappe.get_doc(values)
	lr.insert(ignore_permissions=True)
	return lr


def cancel_donor_lab_results(doc):
	for lr in frappe.get_all("Lab Result", filters={"reff_collection": doc.name}, fields=["name", "docstatus"]):
		if lr.docstatus == 0:
			frappe.delete_doc("Lab Result", lr.name, ignore_permissions=True)
		elif lr.docstatus == 1:
			frappe.get_doc("Lab Result", lr.name).cancel()
