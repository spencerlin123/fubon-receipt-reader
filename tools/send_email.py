"""
send_email.py
-------------
Uses GPT-4o mini to write a notification email as "Bobby" (Fubon Braves billing agent),
then sends it via Gmail API.
"""

import base64
import os
import sys
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build
from openai import OpenAI

from tools.google_auth import get_google_creds

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")
SHEET_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/edit?gid=0#gid=0"

SYSTEM_PROMPT = """# Overview
You are an email expert for the Fubon Braves named Bobby. You will receive invoice information.
Your job is to notify the internal billing team that an invoice was received/sent.
Refer to yourself as "we". For the cost amount, make sure it's in NTD.
If there are notes, please notify them as well.

# Email
Inform the billing team of the invoice. Let them know we have also updated this in the
invoice database, and they can view it here: {sheet_url}

# Output
Output the email body only. No subject line."""


GPT4O_MINI_INPUT_COST  = 0.15 / 1_000_000
GPT4O_MINI_OUTPUT_COST = 0.60 / 1_000_000


def compose_email_body(name: str, date: str, item: str, cost: str, notes: str, drive_link: str) -> tuple[str, float]:
    sheet_id = os.getenv("REIMBURSEMENT_SHEET_ID", "")
    sheet_url = SHEET_URL.format(sheet_id=sheet_id)

    user_content = (
        f"Name: {name}\n"
        f"Date: {date}\n"
        f"Reimbursed item: {item}\n"
        f"Cost: {cost} NTD\n"
        f"Notes: {notes or 'None'}\n"
        f"Digital Copy: {drive_link}"
    )

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(sheet_url=sheet_url)},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )
    usage = response.usage
    email_cost = usage.prompt_tokens * GPT4O_MINI_INPUT_COST + usage.completion_tokens * GPT4O_MINI_OUTPUT_COST
    print(f"  GPT-4o mini (email):      {usage.prompt_tokens} in + {usage.completion_tokens} out → ${email_cost:.4f}")
    return response.choices[0].message.content, email_cost


def _smtp_send(msg: MIMEText, from_email: str, to_email: str) -> None:
    """Send email via Gmail API using OAuth credentials."""
    creds = get_google_creds()
    service = build("gmail", "v1", credentials=creds)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def send_notification(name: str, date: str, item: str, cost: str, notes: str, drive_link: str) -> None:
    to_email = os.getenv("BILLING_EMAIL")
    from_email = os.getenv("GMAIL_SENDER")
    if not to_email or not from_email:
        print("ERROR: BILLING_EMAIL or GMAIL_SENDER not set in .env", file=sys.stderr)
        sys.exit(1)

    print("Composing email with GPT-4o mini...")
    body, email_cost = compose_email_body(name, date, item, cost, notes, drive_link)

    subject = f"{name} - {item} on {date}"

    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to_email
    msg["From"] = from_email
    msg["Subject"] = subject

    _smtp_send(msg, from_email, to_email)
    print(f"Email sent to {to_email}: {subject}")
    return email_cost


def send_notification_multi(name: str, receipts: list[dict], notes: str, drive_link: str) -> float:
    """Send one summary email listing all receipts from a multi-receipt scan."""
    to_email = os.getenv("BILLING_EMAIL")
    from_email = os.getenv("GMAIL_SENDER")
    if not to_email or not from_email:
        print("ERROR: BILLING_EMAIL or GMAIL_SENDER not set in .env", file=sys.stderr)
        sys.exit(1)

    sheet_id = os.getenv("REIMBURSEMENT_SHEET_ID", "")
    sheet_url = SHEET_URL.format(sheet_id=sheet_id)
    total = sum(float(r.get("Total Amount", 0)) for r in receipts)

    incomplete = [i+1 for i, r in enumerate(receipts) if not r.get("Date") or not r.get("Total Amount")]

    receipt_lines = "\n".join(
        f"  {i+1}. {r.get('Category')} on {r.get('Date') or '⚠ DATE MISSING'} — {r.get('Total Amount') or '⚠ AMOUNT MISSING'} NTD"
        for i, r in enumerate(receipts)
    )
    incomplete_note = (
        f"\nWARNING: Receipt(s) {incomplete} could not be fully read. Date or amount is missing — please review the digital copy."
        if incomplete else ""
    )
    user_content = (
        f"Name: {name}\n"
        f"Number of receipts: {len(receipts)}\n"
        f"Receipts:\n{receipt_lines}\n"
        f"Total: {total:.0f} NTD\n"
        f"Notes: {notes or 'None'}\n"
        f"Digital Copy: {drive_link}"
        f"{incomplete_note}"
    )

    print("Composing multi-receipt email with GPT-4o mini...")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(sheet_url=sheet_url)},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )
    usage = response.usage
    email_cost = usage.prompt_tokens * GPT4O_MINI_INPUT_COST + usage.completion_tokens * GPT4O_MINI_OUTPUT_COST
    print(f"  GPT-4o mini (email):      {usage.prompt_tokens} in + {usage.completion_tokens} out → ${email_cost:.4f}")
    body = response.choices[0].message.content

    subject = f"{name} - {len(receipts)} receipts ({total:.0f} NTD total)"
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to_email
    msg["From"] = from_email
    msg["Subject"] = subject

    _smtp_send(msg, from_email, to_email)
    print(f"Email sent to {to_email}: {subject}")
    return email_cost
