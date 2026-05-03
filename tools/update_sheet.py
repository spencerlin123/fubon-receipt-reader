"""
update_sheet.py
---------------
Appends reimbursement rows to the Fubon 單據明細表 Google Sheet.

Columns (A–H):
  A: 日期          — receipt date
  B: 憑證編號      — global auto-incrementing voucher number
  C: 費用類別      — always 交通費
  D: 摘要          — notes (+ drive link appended)
  E: 憑證總額      — receipt total amount
  F: 名字          — person name
  G: 輸入日期      — date the entry was submitted
  H: 重複警告      — "⚠ DUPLICATE" in red if a duplicate was detected

Rows are grouped by person in a fixed order. New rows are inserted
at the end of the person's existing block, not just the sheet bottom.
A 合計 row is maintained at the bottom with a SUM of column E.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build

from tools.google_auth import get_google_creds

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

SHEET_NAME = "單據明細表"
DATA_START_ROW = 5  # 1-indexed; rows 1-4 are headers

# Fixed person order — matches the form dropdown
PERSON_ORDER = ["Spencer", "Archie", "Mike", "Deng", "Stefan", "Aven", "Wang"]

# Colours (match setup_sheet.py)
NAVY      = {"red": 0.031, "green": 0.059, "blue": 0.125}
WHITE     = {"red": 1.0,   "green": 1.0,   "blue": 1.0  }
TEAL      = {"red": 0.0,   "green": 0.784, "blue": 0.847}
AMBER     = {"red": 0.988, "green": 0.729, "blue": 0.012}   # warm gold for 合計 row
DARK_TEXT = {"red": 0.102, "green": 0.102, "blue": 0.180}
RED_BG    = {"red": 0.957, "green": 0.267, "blue": 0.267}   # red for duplicate warning


def _get_service():
    creds = get_google_creds()
    return build("sheets", "v4", credentials=creds)


def _get_sheet_gid(service, sheet_id: str) -> int:
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    return next(
        s["properties"]["sheetId"]
        for s in meta["sheets"]
        if s["properties"]["title"] == SHEET_NAME
    )


def _read_sheet_data(service, sheet_id: str) -> list[dict]:
    """
    Read all existing data rows, excluding the 合計 row.
    Returns list of {"row": int (1-indexed), "name": str}.
    """
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=f"{SHEET_NAME}!A{DATA_START_ROW}:G1000",
    ).execute()
    rows = result.get("values", [])
    data = []
    for i, row in enumerate(rows):
        if not any(str(c).strip() for c in row):
            continue
        col_a = row[0].strip() if row else ""
        if col_a == "合計":
            continue
        name = row[5].strip() if len(row) > 5 else ""
        date = row[0].strip() if row else ""
        amount = str(row[4]).strip() if len(row) > 4 else ""
        data.append({"row": DATA_START_ROW + i, "name": name, "date": date, "amount": amount})
    return data


def _find_insert_row(sheet_data: list[dict], person_name: str) -> int:
    """
    Return the 1-indexed row where a new entry for person_name should be inserted.
    """
    person_rows: dict[str, list[int]] = {p: [] for p in PERSON_ORDER}
    for entry in sheet_data:
        if entry["name"] in person_rows:
            person_rows[entry["name"]].append(entry["row"])

    if person_rows.get(person_name):
        return max(person_rows[person_name]) + 1

    person_idx = PERSON_ORDER.index(person_name) if person_name in PERSON_ORDER else len(PERSON_ORDER)
    insert_after = DATA_START_ROW - 1
    for p in PERSON_ORDER[:person_idx]:
        if person_rows.get(p):
            insert_after = max(person_rows[p])
    return insert_after + 1


def _find_duplicate(sheet_data: list[dict], name: str, date: str, amount: str) -> bool:
    """Return True if a row with the same name, date, and amount already exists."""
    if not date or not amount:
        return False
    try:
        amount_float = float(str(amount).replace(",", "").strip())
    except (ValueError, TypeError):
        return False
    for entry in sheet_data:
        if entry["name"] != name:
            continue
        if entry["date"] != date:
            continue
        try:
            if float(str(entry["amount"]).replace(",", "").strip()) == amount_float:
                return True
        except (ValueError, TypeError):
            continue
    return False


def _global_voucher(sheet_data: list[dict]) -> int:
    return len(sheet_data) + 1


def _parse_amount(amount: str):
    """Convert amount string to float so SUM formula works. Falls back to string."""
    try:
        return float(str(amount).replace(",", "").strip())
    except (ValueError, TypeError):
        return amount


def _insert_rows(service, sheet_id: str, sheet_gid: int, start_row_1indexed: int, count: int) -> None:
    """Insert `count` blank rows at start_row_1indexed, shifting existing rows down."""
    start_idx = start_row_1indexed - 1
    service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": [{
            "insertDimension": {
                "range": {
                    "sheetId": sheet_gid,
                    "dimension": "ROWS",
                    "startIndex": start_idx,
                    "endIndex": start_idx + count,
                },
                "inheritFromBefore": False,
            }
        }]},
    ).execute()


def _renumber_vouchers(service, sheet_id: str, total_rows: int) -> None:
    """Overwrite column B with sequential numbers 1, 2, 3… to keep 憑證編號 in visual order."""
    if total_rows == 0:
        return
    end_row = DATA_START_ROW + total_rows - 1
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{SHEET_NAME}!B{DATA_START_ROW}:B{end_row}",
        valueInputOption="RAW",
        body={"values": [[i + 1] for i in range(total_rows)]},
    ).execute()


def _write_totals_row(service, sheet_id: str, sheet_gid: int, total_rows: int) -> None:
    """
    Write/update the 合計 row directly below all data rows.
    Merges A–D, centres 合計, puts =SUM(...) in column E.
    The row is always pushed down by insertDimension so we just overwrite it.
    """
    totals_row = DATA_START_ROW + total_rows
    last_data_row = totals_row - 1

    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{SHEET_NAME}!A{totals_row}:H{totals_row}",
        valueInputOption="USER_ENTERED",
        body={"values": [["合計", "", "", "", f"=SUM(E{DATA_START_ROW}:E{last_data_row})", "", "", ""]]},
    ).execute()

    row_idx = totals_row - 1  # 0-indexed for batchUpdate
    service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": [
            # Merge A–D
            {"mergeCells": {
                "range": {
                    "sheetId": sheet_gid,
                    "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                    "startColumnIndex": 0, "endColumnIndex": 4,
                },
                "mergeType": "MERGE_ALL",
            }},
            # Format entire totals row (A–G)
            {"repeatCell": {
                "range": {
                    "sheetId": sheet_gid,
                    "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                    "startColumnIndex": 0, "endColumnIndex": 8,
                },
                "cell": {"userEnteredFormat": {
                    "backgroundColor": AMBER,
                    "textFormat": {"foregroundColor": DARK_TEXT, "bold": True, "fontSize": 10},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "borders": {"top": {"style": "SOLID_MEDIUM", "color": TEAL}},
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,borders)",
            }},
        ]},
    ).execute()


def _format_h_cells(service, sheet_id: str, sheet_gid: int, all_rows: list[int], duplicate_rows: list[int]) -> None:
    """
    Explicitly set column H formatting for every inserted row.
    Duplicate rows get red background; all others get a white/clear background.
    This prevents inherited red formatting from bleeding into the next inserted row.
    """
    if not all_rows:
        return
    duplicate_set = set(duplicate_rows)
    requests = []
    for row_1idx in all_rows:
        row_idx = row_1idx - 1
        if row_1idx in duplicate_set:
            fmt = {
                "backgroundColor": RED_BG,
                "textFormat": {"foregroundColor": WHITE, "bold": True},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            }
        else:
            fmt = {
                "backgroundColor": WHITE,
                "textFormat": {"foregroundColor": {"red": 0, "green": 0, "blue": 0}, "bold": False},
                "horizontalAlignment": "LEFT",
                "verticalAlignment": "MIDDLE",
            }
        requests.append({"repeatCell": {
            "range": {
                "sheetId": sheet_gid,
                "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                "startColumnIndex": 7, "endColumnIndex": 8,
            },
            "cell": {"userEnteredFormat": fmt},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
        }})
    service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": requests},
    ).execute()


def append_fubon_row(date: str, amount: str, notes: str, drive_link: str, name: str = "") -> bool:
    """
    Insert a single receipt row into the correct person-grouped position.
    Returns True if a duplicate was detected (row is still inserted).
    """
    sheet_id = os.getenv("FUBON_SHEET_ID")
    if not sheet_id:
        print("ERROR: FUBON_SHEET_ID not set in .env", file=sys.stderr)
        sys.exit(1)

    service = _get_service()
    sheet_gid = _get_sheet_gid(service, sheet_id)
    sheet_data = _read_sheet_data(service, sheet_id)
    duplicate = _find_duplicate(sheet_data, name, date, amount)
    if duplicate:
        print(f"  ⚠ Duplicate detected: {name} | {date} | {amount} NTD already exists in sheet")
    insert_row = _find_insert_row(sheet_data, name)
    voucher = _global_voucher(sheet_data)

    entry_date = datetime.now().strftime("%Y/%m/%d")
    dup_flag = "⚠ DUPLICATE" if duplicate else ""
    摘要 = f"{notes}  {drive_link}".strip() if drive_link else notes
    row = [date, voucher, "交通費", 摘要, _parse_amount(amount), name, entry_date, dup_flag]

    _insert_rows(service, sheet_id, sheet_gid, insert_row, 1)

    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{SHEET_NAME}!A{insert_row}:H{insert_row}",
        valueInputOption="RAW",
        body={"values": [row]},
    ).execute()

    total_rows = len(sheet_data) + 1
    _renumber_vouchers(service, sheet_id, total_rows)
    _write_totals_row(service, sheet_id, sheet_gid, total_rows)

    _format_h_cells(service, sheet_id, sheet_gid, [insert_row], [insert_row] if duplicate else [])

    print(f"Sheet updated: row {insert_row} | voucher #{voucher} | {name} | {date} | {amount} NTD")
    return duplicate


def append_fubon_rows_batch(rows: list[dict], drive_link: str, name: str = "") -> list[int]:
    """
    Insert multiple receipt rows for the same person in a single operation.
    rows: list of {"date": str, "amount": str, "notes": str}
    Returns list of 0-indexed positions within rows that are duplicates.
    """
    sheet_id = os.getenv("FUBON_SHEET_ID")
    if not sheet_id:
        print("ERROR: FUBON_SHEET_ID not set in .env", file=sys.stderr)
        sys.exit(1)

    service = _get_service()
    sheet_gid = _get_sheet_gid(service, sheet_id)
    sheet_data = _read_sheet_data(service, sheet_id)
    duplicate_indices = [
        i for i, r in enumerate(rows)
        if _find_duplicate(sheet_data, name, r.get("date", ""), r.get("amount", ""))
    ]
    for i in duplicate_indices:
        r = rows[i]
        print(f"  ⚠ Duplicate detected: {name} | {r.get('date')} | {r.get('amount')} NTD already exists in sheet")
    insert_row = _find_insert_row(sheet_data, name)
    start_voucher = _global_voucher(sheet_data)
    n = len(rows)

    entry_date = datetime.now().strftime("%Y/%m/%d")
    all_rows = []
    for i, r in enumerate(rows):
        摘要 = f"{r.get('notes', '')}  {drive_link}".strip() if drive_link else r.get("notes", "")
        dup_flag = "⚠ DUPLICATE" if i in duplicate_indices else ""
        all_rows.append([
            r.get("date", ""),
            start_voucher + i,
            "交通費",
            摘要,
            _parse_amount(r.get("amount", "")),
            name,
            entry_date,
            dup_flag,
        ])

    _insert_rows(service, sheet_id, sheet_gid, insert_row, n)

    end_row = insert_row + n - 1
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{SHEET_NAME}!A{insert_row}:H{end_row}",
        valueInputOption="RAW",
        body={"values": all_rows},
    ).execute()

    total_rows = len(sheet_data) + n
    _renumber_vouchers(service, sheet_id, total_rows)
    _write_totals_row(service, sheet_id, sheet_gid, total_rows)

    all_inserted = list(range(insert_row, insert_row + n))
    dup_rows = [insert_row + i for i in duplicate_indices]
    _format_h_cells(service, sheet_id, sheet_gid, all_inserted, dup_rows)

    print(f"Sheet updated: rows {insert_row}–{end_row} | vouchers #{start_voucher}–#{start_voucher + n - 1} | {name}")
    return duplicate_indices
