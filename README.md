## Blood Bank

Blood bank and transfusion management for **Frappe / ERPNext v14 with Healthcare**, by Cibaar Technologies.

It tracks every bag from donor (or supplier) to patient: donor screening, infection tests, collection,
component splitting, storage and expiry, blood requests, crossmatch, issue, bedside transfusion, reactions,
returns and discards, with reports and a stock dashboard.

### Requirements

- Frappe v14, ERPNext v14, Healthcare v14
- No dependency on any other custom app. Lab results are read from any lab doctype set in
  **Blood Bank Settings** (custom *Lab Result*, standard *Lab Test*, or none).

### Install

From GitHub (recommended: clones, pip-installs, adds to apps.txt and builds in one step):

```bash
cd ~/frappe-bench
bench get-app --branch main https://github.com/Rasiintech/blood_bank.git
bench --site <site> install-app blood_bank
```

From a copied folder (no git): bench does not pip-install for you, so do it by hand:

```bash
./env/bin/pip install -e apps/blood_bank
grep -qx blood_bank sites/apps.txt || { [ -n "$(tail -c1 sites/apps.txt)" ] && echo >> sites/apps.txt; echo blood_bank >> sites/apps.txt; }
bench --site <site> install-app blood_bank
```

On sites with the custom **Home Page** doctype, install also creates three tiles: Blood Bank,
Blood Donors and Blood Transfusion. To recreate them: `bench --site <site> execute blood_bank.home_tiles.create_home_tiles`.

Install creates the roles (Blood Bank Officer, Blood Bank Technician, Blood Bank Reception), default
components (Whole Blood, RBC, PLT, FFP, Plasma), screening tests (HIV, HBsAg, HCV, Syphilis, Malaria),
deferral reasons, a screening questionnaire and three storage locations. Review them in
**Blood Bank Settings** and the masters before going live.

### Setup checklist

1. **Blood Bank Settings**: donor limits, testing mode, lab doctype and the test names used in your lab templates.
2. **Blood Component**: set the Billing Item for each component (the lab template item the patient pays).
3. **Blood Storage**: your fridges, freezers and platelet agitator with their temperature ranges.
4. **Users**: give staff the Blood Bank roles; doctors use Physician, nurses Nursing User.
5. **Minimum stock levels** in settings, so the dashboard shows shortages.

### Main flows

| Flow | Documents |
| --- | --- |
| Voluntary donor | Blood Donor → Blood Donor Screening → Blood Donor Test → Blood Donation → (Component Preparation) → Release |
| Replacement donor | Same as above, with Donor Type = Replacement and the patient / Blood Request linked |
| Received blood | Blood Unit Receipt |
| Patient transfusion | Blood Request → Sales Invoice → Blood Crossmatch → Blood Issue → Blood Transfusion |
| Problems | Blood Transfusion Reaction, Blood Unit Return, Blood Unit Discard, Temperature Log |

### License

MIT
