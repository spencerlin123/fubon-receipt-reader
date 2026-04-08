# Fubon Braves Receipt Reader

A Flask web app that automates expense reimbursement for the **Fubon Braves** (Taiwan baseball team). Team members submit receipt images or PDFs via a web form — the system reads the receipt, uploads it to Google Drive, logs it to Google Sheets, and emails the billing team.

Supports single-receipt and multi-receipt (1–10 receipts on one page) submissions.

Also exposes a `POST /api/submit` JSON endpoint for iOS Shortcuts integration.

---

## How It Works

```
User fills out form (name, item, file type, receipt, notes)
       ↓
Receipt uploaded to Google Drive
       ↓
AI extracts date + total amount:
  PDF        → PyPDF2 extracts text → GPT-4o mini parses date + amount
  Image      → Gemini 2.5 Flash OCR → GPT-4o mini structures output
       ↓
Row appended to Google Sheets reimbursement tracker
       ↓
GPT-4o mini writes notification email → sent via Gmail API
```

---

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd fubon-receipt-reader
pip install -r requirements.txt
```

### 2. Configure `.env`

Create a `.env` file in the project root:

```
OPENAI_API_KEY=           # platform.openai.com
GEMINI_API_KEY=           # aistudio.google.com/apikey
GMAIL_SENDER=             # Gmail address that sends notifications
BILLING_EMAIL=            # Email address that receives notifications
DRIVE_FOLDER_ID=          # Google Drive folder ID for receipt storage
REIMBURSEMENT_SHEET_ID=   # Google Sheets spreadsheet ID
```

### 3. Google OAuth

- Place `credentials.json` (downloaded from Google Cloud Console) in the project root
- Required scopes: `drive`, `spreadsheets`, `gmail.send`
- On first run, a browser window opens for authorization
- `token.json` is saved automatically after auth and refreshed as needed

> If you get an `invalid_grant` error, delete `token.json` and resubmit — it will re-authenticate.

### 4. Run

```bash
python app.py
```

Open **http://localhost:5002** in your browser.

---

## File Structure

```
app.py                        # Flask app — main entry point
tools/
  extract_receipt.py          # OCR + AI extraction (Gemini → GPT-4o mini)
  update_sheet.py             # Google Sheets append + Summary tab
  upload_to_drive.py          # Google Drive upload + OAuth
  send_email.py               # Gmail notification (GPT-4o mini writes body)
  receipt_knowledge.json      # AI hints for Taiwan receipt formats
workflows/
  receipt_reimbursement.md    # Full SOP for this system
templates/
  form.html                   # Web UI
static/
  brand_logo.png              # Fubon Braves logo
requirements.txt
```

---

## AI Models

| Task | Model |
|---|---|
| Receipt image OCR | Gemini 2.5 Flash (vision) |
| Structured data extraction | GPT-4o mini |
| Email composition | GPT-4o mini |

---

## Form Fields

| Field | Options |
|---|---|
| Name | Spencer, Aven, Wang, Lion |
| Reimbursed Item | Uber/Taxi from NTUA, Uber/Taxi to NTUA, Uber (Away Game), Meal, Other |
| Submission Type | PDF, Screenshot |
| Receipt | `.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.heic` |
| Notes | Optional free text |

---

## Requirements

- Python 3.11+
- OpenAI API key
- Gemini API key
- Google Cloud project with Drive, Sheets, and Gmail APIs enabled
- `credentials.json` from Google Cloud Console (OAuth 2.0 Desktop App)
