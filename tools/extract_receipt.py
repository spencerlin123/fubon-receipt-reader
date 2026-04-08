"""
extract_receipt.py
------------------
Extracts date and total amount from a receipt.
- PDF: extract text with PyPDF2, then GPT-4o mini parses it
- Image (screenshot): Gemini 2.5 Flash transcribes raw text (OCR), then GPT-4o mini structures it
  Two-step to separate OCR (image → text) from extraction (text → JSON), improving digit accuracy.
  Gemini is used for OCR because it is significantly more accurate on dense Chinese receipt text.
  GPT-4o mini is used for structuring because it only sees clean text — no image hallucination risk.
"""

import base64
import json
import os
import sys
from pathlib import Path

from google import genai
from google.genai import types
import PyPDF2
import pillow_heif

pillow_heif.register_heif_opener()
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")


GPT4O_MINI_INPUT_COST  = 0.15 / 1_000_000   # $ per input token
GPT4O_MINI_OUTPUT_COST = 0.60 / 1_000_000   # $ per output token
GEMINI_INPUT_COST      = 0.075 / 1_000_000  # $ per input token
GEMINI_OUTPUT_COST     = 0.30  / 1_000_000  # $ per output token

KNOWLEDGE_FILE = Path(__file__).parent / "receipt_knowledge.json"


def _load_knowledge() -> dict:
    """Load merchant knowledge base from disk."""
    if KNOWLEDGE_FILE.exists():
        return json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
    return {}


def _build_knowledge_hints() -> str:
    """Load all knowledge base entries and format them as a hints block for the prompt."""
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


def _load_image_data(file_path: str) -> tuple[bytes, str]:
    """Load image file and return (image_bytes, mime_type). Converts HEIC to JPEG."""
    ext = Path(file_path).suffix.lower()
    if ext == ".heic":
        from PIL import Image
        import io
        img = Image.open(file_path)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG")
        return buf.getvalue(), "image/jpeg"
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    with open(file_path, "rb") as f:
        return f.read(), mime_map.get(ext, "image/jpeg")


def _gemini_ocr(image_data: bytes, mime_type: str, ocr_prompt: str) -> tuple[str, float]:
    """Send image to Gemini 2.5 Flash for raw text transcription. Returns (raw_text, cost_usd).
    Retries up to 3 times with exponential backoff on 503 UNAVAILABLE errors."""
    import time
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        print("ERROR: GEMINI_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)
    client = genai.Client(api_key=gemini_api_key)
    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Part.from_bytes(data=image_data, mime_type=mime_type), ocr_prompt],
            )
            usage = response.usage_metadata
            cost = usage.prompt_token_count * GEMINI_INPUT_COST + usage.candidates_token_count * GEMINI_OUTPUT_COST
            print(f"  Gemini 2.5 Flash (OCR):    {usage.prompt_token_count} in + {usage.candidates_token_count} out → ${cost:.4f}")
            return response.text, cost
        except Exception as e:
            if attempt < 3 and "503" in str(e):
                wait = 5 * (2 ** attempt)  # 5s, 10s, 20s
                print(f"  Gemini 503 (attempt {attempt + 1}/4) — retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def extract_from_image(file_path: str) -> tuple[dict, float]:
    """Step 1: Gemini transcribes raw text. Step 2: GPT-4o mini structures it. Returns (result, cost_usd)."""
    image_data, mime_type = _load_image_data(file_path)
    total_cost = 0.0

    # Step 1: Gemini reads the image and transcribes every character — no schema pressure
    ocr_prompt = (
        "Transcribe every piece of text you can see on this receipt exactly as printed. "
        "Include all labels and their associated numbers on the same line, preserving layout. "
        "Do not summarize, interpret, or skip any text. Output plain text only."
    )
    raw_text, cost = _gemini_ocr(image_data, mime_type, ocr_prompt)
    total_cost += cost

    # Step 2: GPT-4o mini extracts structured fields from plain text — no image involved
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    extract_prompt = (
        f"Extract the date and total amount from this receipt text. Return ONLY valid JSON:\n"
        f'{{"Date": "MM/DD/YYYY or empty string if not found", "Total Amount": "number only (no currency symbols), or empty string if not found"}}\n\n'
        f"For the total: look ONLY for '總計' or '合計' — use ONLY the number on the same line immediately after that label. "
        f"NEVER use numbers following: '格式', '隨機碼', '機碼', '統一編號', '貴方', '買方'. "
        f"If neither 總計 nor 合計 is present, check for 'Total' in English. "
        f"If the total cannot be clearly identified, return empty string.\n\n"
        f"For the date: use the transaction timestamp (e.g. 2026-03-12 16:00:50), not the bimonthly period (e.g. 115年03-04月).\n\n"
        f"Receipt text:\n{raw_text[:3000]}"
    )
    extract_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": extract_prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    usage = extract_response.usage
    cost = usage.prompt_tokens * GPT4O_MINI_INPUT_COST + usage.completion_tokens * GPT4O_MINI_OUTPUT_COST
    total_cost += cost
    print(f"  GPT-4o mini (struct):      {usage.prompt_tokens} in + {usage.completion_tokens} out → ${cost:.4f}")
    return json.loads(extract_response.choices[0].message.content), total_cost


CATEGORIES = [
    "Uber/Taxi from NTUA",
    "Uber/Taxi to NTUA",
    "Uber (Away Game)",
    "Meal",
    "Other",
]


def extract_multiple_from_image(file_path: str, receipt_count: int) -> tuple[list[dict], float, list[str]]:
    """
    Step 1: Gemini transcribes all receipts as raw text.
    Step 2: GPT-4o mini extracts structured fields from that text.
    Returns (list of {"Date", "Total Amount", "Category"}, cost_usd, flagged_indices)
    """
    image_data, mime_type = _load_image_data(file_path)
    knowledge_hints = _build_knowledge_hints()
    category_list = ", ".join(CATEGORIES)
    total_cost = 0.0

    # Step 1: Gemini transcribes all visible text — pure OCR, no schema pressure
    ocr_prompt = (
        f"This image contains {receipt_count} receipts glued onto a piece of paper. "
        f"Transcribe every piece of text you can see on each receipt, left to right. "
        f"For each receipt, label it 'Receipt N:' and transcribe all text exactly as printed, "
        f"preserving labels and their associated numbers on the same line. "
        f"Include merchant name, invoice number, all header fields, all line items, and totals. "
        f"Do not summarize, interpret, or skip any text. Output plain text only."
    )
    raw_text, cost = _gemini_ocr(image_data, mime_type, ocr_prompt)
    total_cost += cost
    print(f"  --- RAW OCR ---\n{raw_text}\n  --- END OCR ---")

    # Step 2: GPT-4o mini extracts structured fields from plain text — no image involved
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    extract_prompt = (
        f"Below is transcribed text from {receipt_count} receipts. Extract date, total amount, and category for each.\n\n"

        f"NON-RECEIPT ITEMS: Ignore any delivery slips or order confirmations in the text "
        f"(e.g. a foodpanda slip with an order number like '#3814'). Never use an order number as a total.\n\n"

        f"IDENTICAL-STORE RECEIPTS: If two receipts are from the same store, each has a unique invoice number "
        f"(e.g. WK-51343615 vs WK-51344518). Match the total only to the receipt with that invoice number.\n\n"

        f"{knowledge_hints}\n\n"

        f"FINDING THE TOTAL:\n"
        f"1. The total is the number on the same line immediately after the label '總計' or '合計'.\n"
        f"2. NEVER use the number after '隨機碼', '機碼', '格式', '統一編號', '貴方', or '買方'.\n"
        f"3. If you cannot find '總計' or '合計', check for English 'Total'.\n"
        f"4. If the total is ambiguous, leave it as empty string.\n\n"

        f"HANDWRITTEN RECEIPTS (免用統一發票收據): Cross-reference 總價 column number with 合計新台幣 Chinese text "
        f"(e.g. 七百元 = 700). Both must agree — if not, leave Total Amount as empty string.\n\n"

        f"Categories: {category_list}\n\n"
        f"Return ONLY a valid JSON array with exactly {receipt_count} objects:\n"
        f'[{{"Date": "MM/DD/YYYY or empty string", "Total Amount": "number only or empty string", "Category": "one of the categories above"}}, ...]\n\n'
        f"Transcribed receipt text:\n{raw_text}"
    )
    extract_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": extract_prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    usage = extract_response.usage
    cost = usage.prompt_tokens * GPT4O_MINI_INPUT_COST + usage.completion_tokens * GPT4O_MINI_OUTPUT_COST
    total_cost += cost
    print(f"  GPT-4o mini (struct):      {usage.prompt_tokens} in + {usage.completion_tokens} out → ${cost:.4f}")

    result = json.loads(extract_response.choices[0].message.content)
    # The model may return {"receipts": [...]} or directly a list
    receipts = result if isinstance(result, list) else next(iter(result.values()))
    for i, r in enumerate(receipts):
        print(f"  Receipt {i+1}: {r.get('Date')} | {r.get('Total Amount')} NTD | {r.get('Category')}")

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
