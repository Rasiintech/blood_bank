"""Home Page tiles for sites that use the custom "Home Page" doctype (Cibaar HIS sites).

Runs on install and migrate. It only creates tiles that do not exist yet and never edits a tile
someone has changed. On sites without a "Home Page" doctype it does nothing.

Manual run:  bench --site <site> execute blood_bank.home_tiles.create_home_tiles
"""
import frappe

HOME_PAGE = "Home Page"
ICON = "fas fa-tint"

# (type, link_to, label)
TILES = [
	{
		"name": "Blood Bank",
		"color": "#B71C1C",
		"roles": ["Blood Bank Officer", "Blood Bank Technician"],
		"shortcuts": [
			("Page", "blood-bank-dashboard", "Dashboard"),
			("DocType", "Blood Donor", "Donors"),
			("DocType", "Blood Donor Screening", "Screening"),
			("DocType", "Blood Donor Test", "Donor Test"),
			("DocType", "Blood Donation", "Donation"),
			("DocType", "Blood Unit", "Blood Stock"),
			("DocType", "Blood Request", "Requests"),
			("DocType", "Blood Crossmatch", "Crossmatch"),
			("DocType", "Blood Issue", "Issue"),
			("DocType", "Blood Unit Return", "Returns"),
			("DocType", "Blood Component Preparation", "Split Components"),
			("DocType", "Blood Unit Receipt", "Receive Blood"),
			("DocType", "Blood Unit Discard", "Discard"),
			("DocType", "Blood Storage Temperature Log", "Fridge Temperature"),
			("DocType", "Blood Transfusion", "Transfusions"),
			("DocType", "Blood Transfusion Reaction", "Reactions"),
			("DocType", "Blood Bank Settings", "Settings"),
			("Report", "Blood Stock Summary", "Blood Stock Summary"),
			("Report", "Near Expiry Units", "Near Expiry Units"),
			("Report", "Blood Unit Traceability", "Unit Traceability"),
			("Report", "Blood Donation Register", "Donation Register"),
			("Report", "Donor Deferral Analysis", "Donor Deferral Analysis"),
			("Report", "TTI Screening Summary", "TTI Screening Summary"),
			("Report", "Blood Issue Register", "Issue Register"),
			("Report", "Crossmatch Transfusion Ratio", "Crossmatch Transfusion Ratio"),
			("Report", "Blood Wastage Report", "Wastage Report"),
			("Report", "Transfusion Reaction Register", "Reaction Register"),
		],
	},
	{
		"name": "Blood Donors",
		"color": "#E53935",
		"roles": ["Blood Bank Reception"],
		"shortcuts": [
			("DocType", "Blood Donor", "Donors"),
			("DocType", "Blood Donor Screening", "Screening"),
			("DocType", "Blood Donation", "Donations"),
			("Report", "Blood Donation Register", "Donation Register"),
		],
	},
	{
		"name": "Blood Transfusion",
		"color": "#AD1457",
		"roles": ["Physician", "Nursing User", "Doctor"],
		"shortcuts": [
			("DocType", "Blood Request", "Blood Requests"),
			("DocType", "Blood Transfusion", "Transfusions"),
			("DocType", "Blood Transfusion Reaction", "Reactions"),
			("Report", "Blood Stock Summary", "Blood Stock"),
		],
	},
]


def _field_by_label(meta, *labels):
	wanted = {l.lower() for l in labels}
	for df in meta.fields:
		if (df.label or "").strip().lower() in wanted or df.fieldname in wanted:
			return df.fieldname
	return None


def _tables(meta):
	shortcut_table = roles_table = None
	for df in meta.get_table_fields():
		if df.options == "Has Role":
			roles_table = df.fieldname
		elif frappe.get_meta(df.options).get_field("link_to"):
			shortcut_table = df.fieldname
	return shortcut_table, roles_table


def create_home_tiles(force=False):
	if not frappe.db.exists("DocType", HOME_PAGE):
		return []
	try:
		meta = frappe.get_meta(HOME_PAGE)
		shortcut_table, roles_table = _tables(meta)
		if not shortcut_table:
			return []
		label_f = _field_by_label(meta, "Name", "label", "title")
		color_f = _field_by_label(meta, "Color")
		icon_f = _field_by_label(meta, "Icon")
		public_f = _field_by_label(meta, "Public")
		seq_f = _field_by_label(meta, "Sequence Id")
		cmeta = frappe.get_meta(meta.get_field(shortcut_table).options)
		created = []
		for tile in TILES:
			exists = frappe.db.exists(HOME_PAGE, tile["name"]) or (
				label_f and frappe.db.exists(HOME_PAGE, {label_f: tile["name"]}))
			if exists and not force:
				continue
			doc = frappe.get_doc(HOME_PAGE, exists) if exists else frappe.new_doc(HOME_PAGE)
			if label_f:
				doc.set(label_f, tile["name"])
			if color_f:
				doc.set(color_f, tile["color"])
			if icon_f:
				doc.set(icon_f, ICON)
			if public_f:
				doc.set(public_f, 0)
			if seq_f and doc.get(seq_f) is None:
				doc.set(seq_f, 0)
			doc.set(shortcut_table, [])
			for stype, link_to, label in tile["shortcuts"]:
				if stype == "DocType" and not frappe.db.exists("DocType", link_to):
					continue
				if stype == "Report" and not frappe.db.exists("Report", link_to):
					continue
				if stype == "Page" and not frappe.db.exists("Page", link_to):
					continue
				row = {"type": stype, "link_to": link_to, "label": label}
				if stype == "DocType" and cmeta.get_field("doc_view"):
					row["doc_view"] = "List"
				doc.append(shortcut_table, row)
			if roles_table:
				doc.set(roles_table, [])
				for role in tile["roles"]:
					if frappe.db.exists("Role", role):
						doc.append(roles_table, {"role": role})
			doc.flags.ignore_permissions = True
			doc.flags.ignore_mandatory = True
			doc.save() if exists else doc.insert()
			created.append(doc.name)
		return created
	except Exception:
		frappe.log_error(title="Blood Bank: could not create Home Page tiles")
		return []
