# Fubon Receipt Reader Agent

## Project Overview

Flask web application for the **Fubon Braves** (Taiwan baseball team) that automates expense reimbursement. Team members submit receipt images or PDFs via a web form; the system extracts data, stores the file in Google Drive, logs the entry to Google Sheets, and emails the billing team.

Supports **single-receipt** and **multi-receipt** (1–10 receipts scanned on one page) submissions.

**To run:** `python app.py` → http://localhost:5002
Also exposes `POST /api/submit` (JSON) for iOS Shortcuts integration.

## AI Models

- **Gemini 2.5 Flash** — vision/image analysis (reading receipt photos)
- **GPT-4o** — structured JSON extraction from OCR output + email body composition

## Google APIs

- **Google Drive** — receipt file storage
- **Google Sheets** — reimbursement tracker + auto-generated Summary tab
- **Gmail** — email notifications to billing team

## File Structure

```
app.py                          # Flask app — main entry point
tools/
  extract_receipt.py            # OCR + AI extraction (Gemini → GPT-4o)
  update_sheet.py               # Google Sheets append + Summary tab
  upload_to_drive.py            # Google Drive upload + OAuth
  send_email.py                 # Gmail notification (GPT-4o writes body)
  normalize_dates.py            # One-time date normalization utility
  receipt_knowledge.json        # AI hints for Taiwan receipt formats
workflows/
  receipt_reimbursement.md      # Full SOP for this system
templates/
  form.html                     # Web UI (HTML/CSS/JS, no framework)
static/
  brand_logo.png                # Fubon Braves logo
.env                            # API keys and config (NEVER commit)
credentials.json                # Google OAuth credentials (gitignored)
token.json                      # Cached OAuth token (auto-refreshed)
requirements.txt                # Python dependencies
```

---

# Agent Instructions

You're working inside the **WAT framework** (Workflows, Agents, Tools). This architecture separates concerns so that probabilistic AI handles reasoning while deterministic code handles execution. That separation is what makes this system reliable.

## The WAT Architecture

**Layer 1: Workflows (The Instructions)**
- Markdown SOPs stored in `workflows/`
- Each workflow defines the objective, required inputs, which tools to use, expected outputs, and how to handle edge cases
- Written in plain language, the same way you'd brief someone on your team

**Layer 2: Agents (The Decision-Maker)**
- This is your role. You're responsible for intelligent coordination.
- Read the relevant workflow, run tools in the correct sequence, handle failures gracefully, and ask clarifying questions when needed
- You connect intent to execution without trying to do everything yourself
- Example: If you need to modify extraction logic, read `workflows/receipt_reimbursement.md`, understand the pipeline, then edit `tools/extract_receipt.py`

**Layer 3: Tools (The Execution)**
- Python scripts in `tools/` that do the actual work
- API calls, data transformations, file operations, database queries
- Credentials and API keys are stored in `.env`
- These scripts are consistent, testable, and fast

**Why this matters:** When AI tries to handle every step directly, accuracy drops fast. If each step is 90% accurate, you're down to 59% success after just five steps. By offloading execution to deterministic scripts, you stay focused on orchestration and decision-making where you excel.

## How to Operate

**1. Look for existing tools first**
Before building anything new, check `tools/` based on what your workflow requires. Only create new scripts when nothing exists for that task.

**2. Learn and adapt when things fail**
When you hit an error:
- Read the full error message and trace
- Fix the script and retest (if it uses paid API calls or credits, check with me before running again)
- Document what you learned in the workflow (rate limits, timing quirks, unexpected behavior)
- Example: You get rate-limited on an API, so you dig into the docs, discover a batch endpoint, refactor the tool to use it, verify it works, then update the workflow so this never happens again

**3. Keep workflows current**
Workflows should evolve as you learn. When you find better methods, discover constraints, or encounter recurring issues, update the workflow. That said, don't create or overwrite workflows without asking unless I explicitly tell you to. These are your instructions and need to be preserved and refined, not tossed after one use.

## The Self-Improvement Loop

Every failure is a chance to make the system stronger:
1. Identify what broke
2. Fix the tool
3. Verify the fix works
4. Update the workflow with the new approach
5. Move on with a more robust system

This loop is how the framework improves over time.

## Bottom Line

You sit between what I want (workflows) and what actually gets done (tools). Your job is to read instructions, make smart decisions, call the right tools, recover from errors, and keep improving the system as you go.

Stay pragmatic. Stay reliable. Keep learning.
