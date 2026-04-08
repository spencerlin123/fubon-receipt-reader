# Workflow: Receipt Reimbursement

## Objective
Allow Fubon Braves players and staff to submit reimbursement requests via a web form.
The system automatically reads the receipt, logs it to Google Sheets, and notifies the billing team.

## Setup

### 1. Install dependencies
```bash
cd "Receipt Reader Agent"
pip install -r requirements.txt
```

### 2. Fill in .env
```
OPENAI_API_KEY=        # platform.openai.com
GEMINI_API_KEY=        # aistudio.google.com/apikey
GMAIL_SENDER=          # Gmail address that sends notification
BILLING_EMAIL=         # Who receives the notification (e.g. spencerlinbb@gmail.com)
```
`DRIVE_FOLDER_ID` and `REIMBURSEMENT_SHEET_ID` are pre-filled from the n8n workflow.

### 3. Google OAuth
- Place `credentials.json` in the parent `Claude Code Projects/` directory (already done)
- On first run, a browser window will open for authorization
- Required scopes: `drive.file`, `spreadsheets`, `gmail.send`
- `token.json` is saved inside `Receipt Reader Agent/` after first auth

### 4. Run the app
```bash
python app.py
```
Open **http://localhost:5001** in your browser.

---

## How It Works

```
User fills form (name, item, file type, receipt, notes)
       ↓
Upload receipt → Google Drive (Fubon Braves Receipts folder)
       ↓
Switch on file type:
  PDF        → PyPDF2 extracts text  → GPT-4o parses date + amount
  Screenshot → Gemini 2.5 Flash reads image → GPT-4o structures output
       ↓
Append row to Google Sheet "Reimbursement Tracker"
  Columns: Name | Date | Reimbursed Item | Cost (NTD) | Notes | Digital Copy link
       ↓
GPT-4o writes notification email as "Bobby"
       ↓
Gmail API sends email to billing team
```

## Form Fields
| Field | Type | Options |
|---|---|---|
| Name | Dropdown | Spencer, Aven, Wang, Lion |
| Reimbursed Item | Dropdown | Uber/Taxi from NTUA, Uber/Taxi to NTUA, Uber (Away Game), Meal |
| Submission Type | Dropdown | PDF, Screenshot |
| Receipt | File upload | .pdf, .png, .jpg, .jpeg, .webp |
| Notes | Text | Optional |

## Edge Cases
| Situation | Resolution |
|---|---|
| PDF has no extractable text (scanned) | Falls back to Gemini image analysis automatically |
| OAuth token expired | Delete `token.json` and re-run — browser re-auth prompt appears |
| Gemini API unavailable | `GEMINI_API_KEY` missing → error shown on form |
| Duplicate submission | Sheet appends a new row regardless — user must manually remove duplicates |
