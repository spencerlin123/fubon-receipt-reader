"""
setup_sheet.py
--------------
One-time script to populate and format the Fubon 單據明細表 Google Sheet.

Run once (or re-run to refresh formatting):
    python tools/setup_sheet.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

TOKEN_FILE = Path(__file__).parent.parent / "token.json"
SHEET_NAME = "單據明細表"

# ── Brand colours ──────────────────────────────────────────
NAVY       = {"red": 0.031, "green": 0.059, "blue": 0.125}   # #08101F  rows 1-2 bg
NAVY_MID   = {"red": 0.055, "green": 0.106, "blue": 0.220}   # slightly lighter navy
RED        = {"red": 0.749, "green": 0.098, "blue": 0.098}   # row 3 bg
WHITE      = {"red": 1.0,   "green": 1.0,   "blue": 1.0  }
OFF_WHITE  = {"red": 0.961, "green": 0.961, "blue": 0.961}   # alternating stripe
TEAL       = {"red": 0.0,   "green": 0.784, "blue": 0.847}   # accent border / divider
DARK_TEXT  = {"red": 0.102, "green": 0.102, "blue": 0.180}


def setup():
    sheet_id = os.getenv("FUBON_SHEET_ID")
    if not sheet_id:
        print("ERROR: FUBON_SHEET_ID not set in .env", file=sys.stderr)
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(
        str(TOKEN_FILE),
        ["https://www.googleapis.com/auth/spreadsheets"],
    )
    service = build("sheets", "v4", credentials=creds)

    # ── Get sheet GID ────────────────────────────────────────
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    sheet_gid = next(
        s["properties"]["sheetId"]
        for s in meta["sheets"]
        if s["properties"]["title"] == SHEET_NAME
    )

    # ── Write header values ──────────────────────────────────
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{SHEET_NAME}!A1:F4",
        valueInputOption="RAW",
        body={"values": [
            ["富邦育樂股份有限公司", "", "", "", ""],
            ["單據明細表",           "", "", "", ""],
            ["申請單位：籃球隊",     "", "成本中心代碼：111200", "", ""],
            ["日期", "憑證編號", "費用類別", "摘要", "憑證總額", "名字"],
        ]},
    ).execute()

    def rng(r0, r1, c0, c1):
        return {"sheetId": sheet_gid, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    requests = [
        # ── Merges ────────────────────────────────────────────
        {"mergeCells": {"range": rng(0, 1, 0, 5), "mergeType": "MERGE_ALL"}},  # A1:E1
        {"mergeCells": {"range": rng(1, 2, 0, 5), "mergeType": "MERGE_ALL"}},  # A2:E2
        {"mergeCells": {"range": rng(2, 3, 0, 2), "mergeType": "MERGE_ALL"}},  # A3:B3
        {"mergeCells": {"range": rng(2, 3, 2, 5), "mergeType": "MERGE_ALL"}},  # C3:E3

        # ── Row 1: company name — navy bg, white bold 14pt, centered ──
        {"repeatCell": {
            "range": rng(0, 1, 0, 5),
            "cell": {"userEnteredFormat": {
                "backgroundColor": NAVY,
                "textFormat": {"foregroundColor": WHITE, "bold": True, "fontSize": 14},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
        }},

        # ── Row 2: title — slightly lighter navy, white bold 12pt, centered ──
        {"repeatCell": {
            "range": rng(1, 2, 0, 5),
            "cell": {"userEnteredFormat": {
                "backgroundColor": NAVY_MID,
                "textFormat": {"foregroundColor": WHITE, "bold": True, "fontSize": 12},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
        }},

        # ── Row 3: red bg, white bold, centered both merged cells ──
        {"repeatCell": {
            "range": rng(2, 3, 0, 5),
            "cell": {"userEnteredFormat": {
                "backgroundColor": RED,
                "textFormat": {"foregroundColor": WHITE, "bold": True, "fontSize": 10},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
        }},

        # ── Row 4 cols A-E: full navy header ─────────────────
        {"repeatCell": {
            "range": rng(3, 4, 0, 5),
            "cell": {"userEnteredFormat": {
                "backgroundColor": NAVY,
                "textFormat": {"foregroundColor": WHITE, "bold": True, "fontSize": 10},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "borders": {
                    "bottom": {"style": "SOLID_MEDIUM", "color": TEAL},
                },
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,borders)",
        }},

        # ── Row 4 col F (名字): yellow highlight ─────────────
        {"repeatCell": {
            "range": rng(3, 4, 5, 6),
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": 1.0, "green": 0.949, "blue": 0.2},
                "textFormat": {"foregroundColor": DARK_TEXT, "bold": True, "fontSize": 10},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
        }},

        # ── Row 4 cols G+: clear all formatting ──────────────
        {"repeatCell": {
            "range": rng(3, 4, 6, 26),
            "cell": {"userEnteredFormat": {
                "backgroundColor": WHITE,
                "textFormat": {"foregroundColor": DARK_TEXT, "bold": False, "fontSize": 10},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},

        # ── Row heights ───────────────────────────────────────
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_gid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 40}, "fields": "pixelSize",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_gid, "dimension": "ROWS", "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 36}, "fields": "pixelSize",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_gid, "dimension": "ROWS", "startIndex": 2, "endIndex": 4},
            "properties": {"pixelSize": 28}, "fields": "pixelSize",
        }},

        # ── Column widths ─────────────────────────────────────
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_gid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 110}, "fields": "pixelSize",   # 日期
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_gid, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 90}, "fields": "pixelSize",    # 憑證編號
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_gid, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
            "properties": {"pixelSize": 100}, "fields": "pixelSize",   # 費用類別
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_gid, "dimension": "COLUMNS", "startIndex": 3, "endIndex": 4},
            "properties": {"pixelSize": 300}, "fields": "pixelSize",   # 摘要
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_gid, "dimension": "COLUMNS", "startIndex": 4, "endIndex": 5},
            "properties": {"pixelSize": 110}, "fields": "pixelSize",   # 憑證總額
        }},

        # ── Freeze first 4 rows ───────────────────────────────
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_gid, "gridProperties": {"frozenRowCount": 4}},
            "fields": "gridProperties.frozenRowCount",
        }},
    ]

    service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": requests},
    ).execute()

    print("Sheet formatted successfully.")


if __name__ == "__main__":
    setup()
