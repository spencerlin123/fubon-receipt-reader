"""
setup_summary_tab.py
--------------------
One-time script to populate the Player Summary tab with Sheets formulas
that dynamically update without any API calls on each submission.

Run once: python -m tools.setup_summary_tab

Columns: Player | First Receipt | Latest Receipt | # Days | # Receipts | Total (NTD) | Avg ($) Per Day
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build

from tools.google_auth import get_google_creds

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

SHEET_NAME = "單據明細表"
SUMMARY_SHEET_NAME = "Player Summary"
DATA_START_ROW = 5

PERSON_ORDER = ["Spencer", "Archie", "Mike", "Deng", "Stefan", "Aven", "Wang"]

NAVY      = {"red": 0.031, "green": 0.059, "blue": 0.125}
WHITE     = {"red": 1.0,   "green": 1.0,   "blue": 1.0  }
DARK_TEXT = {"red": 0.102, "green": 0.102, "blue": 0.180}

D = DATA_START_ROW
SRC = SHEET_NAME


def _date_parse(col_a: str) -> str:
    """
    Parse MM/DD/YYYY string stored in column A into a DATE serial.
    Uses RIGHT/LEFT/MID so it's locale-independent (avoids DATEVALUE quirks).
    """
    return f"DATE(RIGHT({col_a},4)*1,LEFT({col_a},2)*1,MID({col_a},4,2)*1)"


def _formula_first(player_cell: str) -> str:
    a = f"'{SRC}'!A${D}:A$1000"
    f = f"'{SRC}'!F${D}:F$1000"
    return (
        f"=IFERROR(TEXT(MIN(ARRAYFORMULA(IF(({f}={player_cell})*({a}<>\"\"),"
        f"{_date_parse(a)},\"\"))),"
        f"\"MM/DD/YYYY\"),\"\")"
    )


def _formula_latest(player_cell: str) -> str:
    a = f"'{SRC}'!A${D}:A$1000"
    f = f"'{SRC}'!F${D}:F$1000"
    return (
        f"=IFERROR(TEXT(MAX(ARRAYFORMULA(IF(({f}={player_cell})*({a}<>\"\"),"
        f"{_date_parse(a)},\"\"))),"
        f"\"MM/DD/YYYY\"),\"\")"
    )


def _formula_days(row: int) -> str:
    # Inclusive day count: latest - first + 1 (blank if no receipts)
    return f"=IFERROR(DATEVALUE(C{row})-DATEVALUE(B{row})+1,\"\")"


def _formula_count(player_cell: str) -> str:
    return f"=COUNTIF('{SRC}'!F${D}:F$1000,{player_cell})"


def _formula_total(player_cell: str) -> str:
    return f"=SUMIF('{SRC}'!F${D}:F$1000,{player_cell},'{SRC}'!E${D}:E$1000)"


def _formula_avg(row: int) -> str:
    # Total / # Receipts; blank if no receipts
    return f"=IFERROR(F{row}/E{row},\"\")"


def setup():
    sheet_id = os.getenv("FUBON_SHEET_ID")
    if not sheet_id:
        print("ERROR: FUBON_SHEET_ID not set in .env", file=sys.stderr)
        sys.exit(1)

    creds = get_google_creds()
    service = build("sheets", "v4", credentials=creds)

    # Get or create the summary sheet
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    summary_gid = None
    for s in meta["sheets"]:
        if s["properties"]["title"] == SUMMARY_SHEET_NAME:
            summary_gid = s["properties"]["sheetId"]
            break
    if summary_gid is None:
        resp = service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": SUMMARY_SHEET_NAME}}}]},
        ).execute()
        summary_gid = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
        print(f"  Created '{SUMMARY_SHEET_NAME}' tab")
    else:
        print(f"  Found existing '{SUMMARY_SHEET_NAME}' tab")

    # Clear existing content
    service.spreadsheets().values().clear(
        spreadsheetId=sheet_id,
        range=f"{SUMMARY_SHEET_NAME}!A1:Z1000",
    ).execute()

    # Build values: header + one row per player
    header = [["Player", "First Receipt", "Latest Receipt", "# Days", "# Receipts", "Total (NTD)", "Avg ($) Per Receipt"]]
    data_rows = []
    for i, name in enumerate(PERSON_ORDER):
        row_num = i + 2  # row 1 is header
        pc = f"A{row_num}"
        data_rows.append([
            name,
            _formula_first(pc),
            _formula_latest(pc),
            _formula_days(row_num),
            _formula_count(pc),
            _formula_total(pc),
            _formula_avg(row_num),
        ])

    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{SUMMARY_SHEET_NAME}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": header + data_rows},
    ).execute()

    n = len(PERSON_ORDER)
    requests = [
        # Header: navy background, white bold text
        {"repeatCell": {
            "range": {
                "sheetId": summary_gid,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": 7,
            },
            "cell": {"userEnteredFormat": {
                "backgroundColor": NAVY,
                "textFormat": {"foregroundColor": WHITE, "bold": True, "fontSize": 10},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
        }},
        # Data rows: white background, clean text, left-aligned
        {"repeatCell": {
            "range": {
                "sheetId": summary_gid,
                "startRowIndex": 1, "endRowIndex": 1 + n,
                "startColumnIndex": 0, "endColumnIndex": 7,
            },
            "cell": {"userEnteredFormat": {
                "backgroundColor": WHITE,
                "textFormat": {"foregroundColor": DARK_TEXT, "bold": False, "fontSize": 10},
                "horizontalAlignment": "LEFT",
                "verticalAlignment": "MIDDLE",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
        }},
        # Center-align numeric columns: D=# Days, E=# Receipts, F=Total, G=Avg
        {"repeatCell": {
            "range": {
                "sheetId": summary_gid,
                "startRowIndex": 1, "endRowIndex": 1 + n,
                "startColumnIndex": 3, "endColumnIndex": 7,
            },
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat(horizontalAlignment)",
        }},
        # Auto-resize all 7 columns
        {"autoResizeDimensions": {
            "dimensions": {
                "sheetId": summary_gid,
                "dimension": "COLUMNS",
                "startIndex": 0, "endIndex": 7,
            }
        }},
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": requests},
    ).execute()

    print(f"  Player Summary set up: {', '.join(PERSON_ORDER)}")
    print("  Columns: Player | First Receipt | Latest Receipt | # Days | # Receipts | Total (NTD) | Avg ($) Per Receipt")


if __name__ == "__main__":
    setup()
