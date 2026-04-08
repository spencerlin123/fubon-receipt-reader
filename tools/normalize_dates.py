"""
normalize_dates.py
------------------
One-time script to normalize all existing dates in the Reimbursement Tracker
Google Sheet to MM/DD/YYYY format.

Usage:
    python tools/normalize_dates.py
"""

import os
import sys
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from openai import OpenAI

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

TOKEN_FILE = Path(__file__).parent.parent / "token.json"


def normalize_date(client: OpenAI, raw_date: str) -> str:
    """Convert any date string to MM/DD/YYYY using GPT-4o."""
    if not raw_date or raw_date.strip() == "":
        return raw_date

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": f"Convert this date to MM/DD/YYYY format. Return ONLY the formatted date, nothing else: {raw_date}"
        }],
        temperature=0,
    )
    return response.choices[0].message.content.strip()


def main():
    sheet_id = os.getenv("REIMBURSEMENT_SHEET_ID")
    if not sheet_id:
        print("ERROR: REIMBURSEMENT_SHEET_ID not set in .env", file=sys.stderr)
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(
        str(TOKEN_FILE),
        ["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)

    try:
        ws = sh.worksheet("Reimbursement Tracker")
    except gspread.WorksheetNotFound:
        ws = sh.sheet1

    all_values = ws.get_all_values()
    if not all_values:
        print("Sheet is empty.")
        return

    headers = all_values[0]
    rows = all_values[1:]

    if "Date" not in headers:
        print(f"ERROR: No 'Date' column found. Headers: {headers}", file=sys.stderr)
        sys.exit(1)

    date_col_index = headers.index("Date")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    updated = 0
    for i, row in enumerate(rows, start=2):  # start=2 because row 1 is header
        if date_col_index >= len(row):
            continue

        raw_date = row[date_col_index]
        normalized = normalize_date(client, raw_date)

        if normalized != raw_date:
            # Column letters: A=1, B=2, etc.
            col_letter = chr(ord("A") + date_col_index)
            ws.update_acell(f"{col_letter}{i}", normalized)
            print(f"  Row {i}: '{raw_date}' → '{normalized}'")
            updated += 1
        else:
            print(f"  Row {i}: '{raw_date}' ✓ already correct")

    print(f"\nDone. {updated} date(s) updated.")


if __name__ == "__main__":
    main()
