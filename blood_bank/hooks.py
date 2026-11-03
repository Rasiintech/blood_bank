from . import __version__ as app_version  # noqa: F401

app_name = "blood_bank"
app_title = "Blood Bank"
app_publisher = "Cibaar Technologies"
app_description = "Blood bank and transfusion management for Frappe Healthcare v14"
app_email = "cibaartechnologies@gmail.com"
app_license = "MIT"
required_apps = ["erpnext", "healthcare"]

# Install
before_install = "blood_bank.install.before_install"
after_install = "blood_bank.install.after_install"
after_migrate = "blood_bank.install.after_migrate"

# Client scripts on core doctypes
doctype_js = {
	"Patient": "public/js/patient.js",
	"Sales Invoice": "public/js/sales_invoice.js",
	"Patient Encounter": "public/js/patient_encounter.js",
	"Inpatient Record": "public/js/inpatient_record.js",
}

# Document events
doc_events = {
	"Sales Invoice": {
		"on_submit": "blood_bank.billing.on_sales_invoice_change",
		"on_cancel": "blood_bank.billing.on_sales_invoice_change",
		"on_update_after_submit": "blood_bank.billing.on_sales_invoice_change",
		"on_trash": "blood_bank.blood_bank.doctype.blood_donor_screening.blood_donor_screening.unlink_order",
	},
	"Sample Collection": {
		# HIS bridge: lets free donor samples (no invoice) submit; HIS code is not changed
		"before_submit": "blood_bank.integrations.his.apply",
		"before_cancel": "blood_bank.integrations.his.apply",
		"on_cancel": "blood_bank.blood_bank.doctype.blood_donor_screening.blood_donor_screening.unlink_order",
		"on_trash": "blood_bank.blood_bank.doctype.blood_donor_screening.blood_donor_screening.unlink_order",
	},
	"Payment Entry": {
		"on_submit": "blood_bank.billing.on_payment_change",
		"on_cancel": "blood_bank.billing.on_payment_change",
	},
	"*": {
		"on_submit": "blood_bank.lab.on_lab_document_submit",
	},
}

scheduler_events = {
	"hourly": [
		"blood_bank.tasks.expire_units",
		"blood_bank.tasks.release_expired_reservations",
	],
	"daily": [
		"blood_bank.tasks.end_expired_deferrals",
	],
}

jinja = {
	"methods": [
		"blood_bank.barcode.code128_svg",
	],
}

fixtures = []
