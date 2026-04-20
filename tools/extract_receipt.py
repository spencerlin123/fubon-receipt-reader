"""
extract_receipt.py
------------------
Extracts date and total amount from a receipt.
- PDF: extract text with PyPDF2, then GPT-4o mini parses it
- Image (screenshot): Gemini 2.5 Flash reads the image and returns structured JSON directly (single pass)
"""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google import genai
from google.genai import types
import PyPDF2
import pillow_heif

pillow_heif.register_heif_opener()
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")


GPT4O_MINI_INPUT_COST  = 0.15  / 1_000_000  # $ per input token
GPT4O_MINI_OUTPUT_COST = 0.60  / 1_000_000  # $ per output token
GEMINI_INPUT_COST      = 0.075 / 1_000_000  # $ per input token
GEMINI_OUTPUT_COST     = 0.30  / 1_000_000  # $ per output token

KNOWLEDGE_FILE = Path(__file__).parent / "receipt_knowledge.json"


def _load_knowledge() -> dict:
    if KNOWLEDGE_FILE.exists():
        return json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
    return {}


def _build_knowledge_hints() -> str:
    knowledge = _load_knowledge()
    if not knowledge:
        return ""
    lines = ["Known receipt type hints (apply whichever matches the receipt you are reading):"]
    for key, entry in knowledge.items():
        lines.append(f"  - {key}: {entry['hints']}")
    return "\n".join(lines)


def _extract_fields_with_gpt(client: OpenAI, raw_text: str) -> tuple[dict, float]:
    """Use GPT-4o mini to pull date and total amount from raw text. Returns (result, cost_usd)."""
    prompt = f"""Extract the following from this receipt text. Return ONLY valid JSON.

{{
  "Date": "the receipt date formatted as MM/DD/YYYY (e.g. 03/20/2026), or empty string if not found",
  "Total Amount": "the total amount as a number only (no currency symbols), or empty string if not found"
}}

RULES:
- For Uber receipts: use the bold "Total" at the top (the final charged amount after discounts). Do NOT use "Trip fare" — that is the pre-discount amount. Discounts like "Uber One Credits" reduce the total below the trip fare.
- For the date: use the ride/transaction date, not the payment timestamp if they differ.

Receipt text:
{raw_text[:3000]}
"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    usage = response.usage
    cost = usage.prompt_tokens * GPT4O_MINI_INPUT_COST + usage.completion_tokens * GPT4O_MINI_OUTPUT_COST
    print(f"  GPT-4o mini (extraction): {usage.prompt_tokens} in + {usage.completion_tokens} out → ${cost:.4f}")
    return json.loads(response.choices[0].message.content), cost


def extract_from_pdf(file_path: str) -> tuple[dict, float]:
    """Extract text from PDF, then parse with GPT-4o mini. Returns (result, cost_usd)."""
    text = ""
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() or ""

    if not text.strip():
        print("WARNING: No text extracted from PDF. Falling back to image analysis.", file=sys.stderr)
        return extract_from_image(file_path)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _extract_fields_with_gpt(client, text)


def _load_image_data(file_path: str, crop_top_fraction: float = 1.0) -> tuple[bytes, str]:
    """Load image file and return (image_bytes, mime_type). Converts HEIC to JPEG.
    crop_top_fraction: if < 1.0, crop to only the top portion of the image."""
    from PIL import Image
    import io
    ext = Path(file_path).suffix.lower()
    img = Image.open(file_path).convert("RGB")
    if crop_top_fraction < 1.0:
        w, h = img.size
        img = img.crop((0, 0, w, int(h * crop_top_fraction)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue(), "image/jpeg"


def _gemini_call(image_data: bytes, mime_type: str, prompt: str, response_mime_type: str = "text/plain") -> tuple[str, float]:
    """Send image + prompt to Gemini 2.5 Flash. Returns (response_text, cost_usd)."""
    import time
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        print("ERROR: GEMINI_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)
    client = genai.Client(api_key=gemini_api_key)
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Part.from_bytes(data=image_data, mime_type=mime_type), prompt],
                config=types.GenerateContentConfig(
                    response_mime_type=response_mime_type,
                    http_options=types.HttpOptions(timeout=90000),
                ),
            )
            usage = response.usage_metadata
            cost = usage.prompt_token_count * GEMINI_INPUT_COST + usage.candidates_token_count * GEMINI_OUTPUT_COST
            print(f"  Gemini 2.5 Flash:          {usage.prompt_token_count} in + {usage.candidates_token_count} out → ${cost:.4f}")
            return response.text, cost
        except Exception as e:
            if attempt < 2:
                wait = 3 * (attempt + 1)
                print(f"  Gemini error (attempt {attempt + 1}/3): {e} — retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def extract_from_image(file_path: str) -> tuple[dict, float]:
    """Single pass: Gemini 2.5 Flash reads the image and extracts date + total directly."""
    image_data, mime_type = _load_image_data(file_path)

    prompt = (
        "Look at this receipt image and extract the date and total amount. Return ONLY valid JSON:\n"
        '{"Date": "MM/DD/YYYY or empty string if not found", "Total Amount": "number only (no currency symbols), or empty string if not found"}\n\n'
        "RULES:\n"
        "- For the total: find '總計' or '合計' and use the number immediately next to or below that label.\n"
        "- '格式' is a format code (small number like 25) — NEVER use it as the total.\n"
        "- NEVER use numbers after: '格式', '隨機碼', '機碼', '統一編號', '貴方', '買方'.\n"
        "- If neither '總計' nor '合計' is present, look for English 'Total'.\n"
        "- For Uber receipts: the bold 'Total' at the top of the receipt (e.g. NT$107.00) is the FINAL amount after all discounts. "
        "Do NOT use 'Trip fare' — that is the pre-discount fare. Discounts like 'Uber One Credits' reduce the total below the trip fare.\n"
        "- For the date: use the transaction timestamp (e.g. 2026-03-12 16:00:50), not the bimonthly period (e.g. 115年03-04月).\n"
        "- If the total cannot be clearly identified, return empty string."
    )

    raw, cost = _gemini_call(image_data, mime_type, prompt, response_mime_type="application/json")
    return json.loads(raw), cost


CATEGORIES = [
    "Uber/Taxi",
    "Meal",
    "Other",
]


def _identify_invoices(image_data: bytes, mime_type: str, receipt_count: int) -> tuple[list[str], float]:
    """Pass 1: identify all invoice numbers left to right."""
    prompt = (
        f"This image contains {receipt_count} receipts laid side by side. "
        f"Each receipt has an invoice number printed in large text near the top (e.g. XJ-07462440, WK-51343615, WC-27543875). "
        f"List all {receipt_count} invoice numbers from left to right. "
        f"Ignore delivery slips (e.g. foodpanda). "
        f'Return ONLY valid JSON: {{"invoices": ["INVOICE1", "INVOICE2", ...]}}'
    )
    raw, cost = _gemini_call(image_data, mime_type, prompt, response_mime_type="application/json")
    result = json.loads(raw)
    return result.get("invoices", []), cost


def _extract_single_invoice(image_data: bytes, mime_type: str, invoice: str, category_list: str, knowledge_hints: str) -> tuple[dict, float]:
    """Pass 2: extract date, total, and category for one specific invoice number."""
    prompt = (
        f"In this image, find the receipt with invoice number {invoice}.\n"
        f"Below the invoice number is a 3×2 grid:\n"
        f"  [ timestamp ]  [ 格式: XX  ]\n"
        f"  [ 隨機碼   ]  [ 總計: XXX ]\n"
        f"  [ 賣方     ]  [ 買方      ]\n\n"
        f"Extract ONLY from the receipt with invoice number {invoice} — ignore all other receipts.\n\n"
        f"DATE: the timestamp in the top-left cell (e.g. 2026-01-24 17:05:08) — NOT the 115年MM-DD月 period.\n"
        f"TOTAL: the number next to '總計' in the middle-right cell. "
        f"CRITICAL — READING THE TOTAL: After locating '總計', scan the ENTIRE cell from LEFT to RIGHT. "
        f"Totals in Taiwan are typically 3–5 digits. Start reading from the LEFTMOST digit — do NOT skip any digit. "
        f"Commas are thousands separators: '5,729' = 5729 (NOT 729). '1,234' = 1234. '12,345' = 12345. "
        f"The digit before the comma is part of the number — never drop it. "
        f"Currency symbols like '$' or 'NT$' are NOT digits — strip them: '$525' = 525 (NOT 5525). "
        f"NEVER use the number next to '格式' (always ~25). "
        f"{knowledge_hints}\n\n"
        f"CATEGORY: choose one from: {category_list}\n\n"
        f'Return ONLY valid JSON: {{"Invoice": "{invoice}", "Date": "MM/DD/YYYY or empty", "Total Amount": "digits only or empty", "Category": "category"}}'
    )
    raw, cost = _gemini_call(image_data, mime_type, prompt, response_mime_type="application/json")
    result = json.loads(raw)
    return result, cost


def extract_multiple_from_image(file_path: str, receipt_count: int) -> tuple[list[dict], float, list[str]]:
    """
    Two-pass parallelized extraction:
      Pass 1: identify all invoice numbers (1 call)
      Pass 2: extract date/total/category per invoice in parallel (N calls)
    Returns (list of {"Date", "Total Amount", "Category"}, cost_usd, flagged_indices)
    """
    image_data, mime_type = _load_image_data(file_path, crop_top_fraction=0.40)
    knowledge_hints = _build_knowledge_hints()
    category_list = ", ".join(CATEGORIES)
    total_cost = 0.0

    # Pass 1: get invoice numbers
    print("  Pass 1: identifying invoice numbers...")
    invoices, cost1 = _identify_invoices(image_data, mime_type, receipt_count)
    total_cost += cost1
    print(f"  Found: {invoices}")

    # Pass 2: parallel targeted extraction per invoice
    print("  Pass 2: extracting each receipt in parallel...")
    results_by_invoice = {}
    with ThreadPoolExecutor(max_workers=receipt_count) as executor:
        futures = {
            executor.submit(_extract_single_invoice, image_data, mime_type, inv, category_list, knowledge_hints): inv
            for inv in invoices
        }
        for future in as_completed(futures):
            inv = futures[future]
            result, cost = future.result()
            total_cost += cost
            results_by_invoice[inv] = result

    # Preserve left-to-right order from Pass 1
    receipts = [results_by_invoice[inv] for inv in invoices if inv in results_by_invoice]

    for i, r in enumerate(receipts):
        print(f"  Receipt {i+1} [{r.get('Invoice', '?')}]: {r.get('Date')} | {r.get('Total Amount')} NTD | {r.get('Category')}")

    flagged = [f"Receipt {i+1}" for i, r in enumerate(receipts) if not r.get("Date") or not r.get("Total Amount")]
    return receipts, total_cost, flagged


def extract_receipt_data(file_path: str, file_type: str) -> tuple[dict, float]:
    """
    Main entry point.
    file_type: "PDF" or "Screenshot"
    Returns: ({"Date": "...", "Total Amount": "..."}, cost_usd)
    """
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    if file_type == "PDF":
        result, cost = extract_from_pdf(file_path)
    else:
        result, cost = extract_from_image(file_path)

    print(f"Extracted — Date: {result.get('Date')} | Amount: {result.get('Total Amount')}")
    return result, cost
