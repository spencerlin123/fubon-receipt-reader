"""
app.py
------
Flask web app for the Fubon Braves Reimbursement Request system.
Serves the form and orchestrates the full pipeline on submission:
  1. Upload receipt to Google Drive
  2. Extract date + amount (PDF → PyPDF2+GPT-4o | Image → Gemini+GPT-4o)
  3. Append row to Google Sheet
  4. Compose and send notification email via Gmail

Usage:
    python app.py
    # Open http://localhost:5001 in your browser
"""

import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# Add tools to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from tools.extract_receipt import extract_multiple_from_image, extract_receipt_data
from tools.update_sheet import append_fubon_row, append_fubon_rows_batch
from tools.upload_to_drive import upload_receipt

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fubon-braves-reimb-secret")


def _compress_image(tmp_path: str, original_filename: str, max_width: int = 1000) -> str:
    """
    Resize and compress image in-place to reduce Drive upload size.
    Returns the updated filename (always .jpg after compression).
    PDFs are skipped unchanged.
    """
    ext = Path(original_filename).suffix.lower()
    if ext == ".pdf":
        return original_filename
    import pillow_heif
    pillow_heif.register_heif_opener()
    from PIL import Image
    img = Image.open(tmp_path)
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    img.convert("RGB").save(tmp_path, "JPEG", quality=85, optimize=True)
    compressed_name = Path(original_filename).stem + ".jpg"
    print(f"  Compressed to {img.width}px wide JPEG → {compressed_name}")
    return compressed_name

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic"}


def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    return render_template("form.html")


@app.route("/submit", methods=["POST"])
def submit():
    name = request.form.get("name", "").strip()
    notes = request.form.get("notes", "").strip()
    receipt_file = request.files.get("receipt")
    receipt_count = max(1, int(request.form.get("receipt_count", 1) or 1))
    multi = receipt_count > 1

    # Auto-detect file type from extension
    ext = Path(receipt_file.filename).suffix.lower() if receipt_file else ""
    file_type = "PDF" if ext == ".pdf" else "Screenshot"

    if not all([name, receipt_file]):
        flash("All fields are required.", "error")
        return redirect(url_for("index"))

    if not allowed_file(receipt_file.filename):
        flash("Only PDF, PNG, JPG, or WebP files are accepted.", "error")
        return redirect(url_for("index"))

    # Save file to temp location for processing
    suffix = Path(receipt_file.filename).suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        receipt_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        t_start = time.time()
        print(f"\n{'='*50}")
        print(f"New submission: {name} | {'Multi x'+str(receipt_count) if multi else 'Single'} | {file_type}")

        # Compress image before any processing (skipped for PDFs)
        drive_filename = _compress_image(tmp_path, receipt_file.filename)

        if multi:
            # ── Multi-receipt path ──────────────────────────
            # Step 1+2: Extract and upload to Drive in parallel
            print(f"Step 1+2: Extracting {receipt_count} receipts and uploading to Drive in parallel...")
            t1 = time.time()
            with ThreadPoolExecutor(max_workers=2) as executor:
                future_extract = executor.submit(extract_multiple_from_image, tmp_path, receipt_count)
                future_drive = executor.submit(upload_receipt, tmp_path, drive_filename, name, "Receipts")
                receipts, cost_extract, flagged = future_extract.result()
                uploaded = future_drive.result()
            drive_link = uploaded.get("webViewLink", "")
            print(f"  Step 1+2 done: {time.time() - t1:.1f}s")

            # Build rows for batch sheet update
            rows_data = []
            for r in receipts:
                missing_r = [f for f, v in [("date", r.get("Date")), ("amount", r.get("Total Amount"))] if not v]
                row_notes = (f"⚠ REVIEW NEEDED — {' and '.join(missing_r)} could not be extracted. " + notes).strip() if missing_r else notes
                rows_data.append({"date": r.get("Date", ""), "amount": r.get("Total Amount", ""), "notes": row_notes})

            # Step 3: Sheet update
            print("Step 3: Updating sheet...")
            t2 = time.time()
            duplicate_indices = append_fubon_rows_batch(rows_data, drive_link, name)
            cost_email = 0
            print(f"  Step 3 done: {time.time() - t2:.1f}s")

            total_ntd = sum(float(r.get("Total Amount", 0)) for r in receipts)
            total_cost = cost_extract + cost_email
            print(f"{'─'*50}")
            print(f"✓ Submission complete.  Total API cost: ${total_cost:.4f}  |  Time: {time.time() - t_start:.1f}s")
            flash(f"{len(receipts)} receipts submitted for {name} — {total_ntd:.0f} NTD total", "success")
            if duplicate_indices:
                dup_labels = ", ".join(f"Receipt {i+1}" for i in duplicate_indices)
                flash(f"⚠ Possible duplicate: {dup_labels} may already be in the sheet. Please verify.", "error")
            if flagged:
                flash(f"⚠ Receipt format may have changed for: {', '.join(flagged)}. Please verify the amounts.", "error")

        else:
            # ── Single-receipt path ───────────────────────────
            # Step 1+2: Extract and upload to Drive in parallel
            print(f"Step 1+2: Extracting data and uploading to Drive in parallel...")
            t1 = time.time()
            with ThreadPoolExecutor(max_workers=2) as executor:
                future_extract = executor.submit(extract_receipt_data, tmp_path, file_type)
                future_drive = executor.submit(upload_receipt, tmp_path, drive_filename, name, "Receipt")
                extracted, cost_extract = future_extract.result()
                uploaded = future_drive.result()
            drive_link = uploaded.get("webViewLink", "")
            print(f"  Step 1+2 done: {time.time() - t1:.1f}s")

            date = extracted.get("Date", "")
            amount = extracted.get("Total Amount", "")

            missing = []
            if not date:   missing.append("date")
            if not amount: missing.append("amount")
            sheet_notes = (f"⚠ REVIEW NEEDED — {' and '.join(missing)} could not be extracted. " + notes).strip() if missing else notes

            # Step 3: Sheet update
            print("Step 3: Updating sheet...")
            t2 = time.time()
            duplicate = append_fubon_row(date or "Unknown", amount or "Unknown", sheet_notes, drive_link, name)
            cost_email = 0
            print(f"  Step 3 done: {time.time() - t2:.1f}s")

            total_cost = cost_extract + cost_email
            print(f"{'─'*50}")
            print(f"✓ Submission complete.  Total API cost: ${total_cost:.4f}  |  Time: {time.time() - t_start:.1f}s")
            flash(f"Request submitted successfully! {name} — {(amount or 'Unknown')} NTD on {date or 'Unknown'}", "success")
            if duplicate:
                flash(f"⚠ Possible duplicate: a receipt for {amount} NTD on {date} already exists for {name}. Please verify.", "error")
            if missing:
                flash(f"Warning: {' and '.join(missing)} could not be read from this receipt — please verify manually and update the sheet.", "error")

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        flash(f"Something went wrong: {str(e)}", "error")

    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    return redirect(url_for("index"))


@app.route("/api/submit", methods=["POST"])
def api_submit():
    """JSON-returning endpoint for iOS Shortcuts (avoids redirect issues)."""
    name = request.form.get("name", "").strip()
    notes = request.form.get("notes", "").strip()
    receipt_file = request.files.get("receipt")

    if not name or not receipt_file:
        return jsonify({"status": "error", "message": "Missing required fields (name, receipt)."}), 400

    if not allowed_file(receipt_file.filename):
        return jsonify({"status": "error", "message": "Invalid file type. Use PDF, PNG, JPG, or WebP."}), 400

    ext = Path(receipt_file.filename).suffix.lower()
    file_type = "PDF" if ext == ".pdf" else "Screenshot"

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        receipt_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        t_start = time.time()
        print(f"\n{'='*50}")
        print(f"[API] New submission: {name} | {file_type}")

        drive_filename = _compress_image(tmp_path, receipt_file.filename)

        print("Step 1+2: Extracting data and uploading to Drive in parallel...")
        t1 = time.time()
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_extract = executor.submit(extract_receipt_data, tmp_path, file_type)
            future_drive = executor.submit(upload_receipt, tmp_path, drive_filename, name, "Receipt")
            extracted, cost_extract = future_extract.result()
            uploaded = future_drive.result()
        drive_link = uploaded.get("webViewLink", "")
        print(f"  Step 1+2 done: {time.time() - t1:.1f}s")

        date = extracted.get("Date", "")
        amount = extracted.get("Total Amount", "")

        missing = []
        if not date:   missing.append("date")
        if not amount: missing.append("amount")
        sheet_notes = (f"⚠ REVIEW NEEDED — {' and '.join(missing)} could not be extracted. " + notes).strip() if missing else notes

        print("Step 3: Updating sheet...")
        t2 = time.time()
        duplicate = append_fubon_row(date or "Unknown", amount or "Unknown", sheet_notes, drive_link, name)
        cost_email = 0
        print(f"  Step 3 done: {time.time() - t2:.1f}s")

        total_cost = cost_extract + cost_email
        print(f"{'─'*50}")
        print(f"✓ Submission complete.  Total API cost: ${total_cost:.4f}  |  Time: {time.time() - t_start:.1f}s")

        message = f"Submitted! {name} — {amount or 'Unknown'} NTD on {date or 'Unknown'}"
        if duplicate:
            message += f" ⚠ Possible duplicate — a receipt for {amount} NTD on {date} already exists for {name}. Please verify."
        if missing:
            message += f" ⚠ Could not read: {' and '.join(missing)} — please verify."
        return jsonify({"status": "success", "message": message})

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": str(e)}), 500

    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5002))
    print(f"Starting Fubon Braves Reimbursement app on http://localhost:{port}")
    app.run(debug=True, host="0.0.0.0", port=port)
