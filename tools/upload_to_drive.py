"""
upload_to_drive.py
------------------
Uploads a receipt file to the "Fubon Braves Receipts" Google Drive folder.
Returns the file's web view link for logging in the sheet.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from tools.google_auth import get_google_creds

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")


def _get_subfolder_id(service, parent_folder_id: str, name: str) -> str:
    """
    Look for a subfolder matching `name` inside parent_folder_id.
    Returns the subfolder's ID if found, otherwise falls back to parent_folder_id.
    """
    query = (
        f"'{parent_folder_id}' in parents "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and name = '{name}' "
        f"and trashed = false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get("files", [])
    if folders:
        print(f"  Uploading to subfolder: {name}/")
        return folders[0]["id"]
    print(f"  No subfolder found for '{name}', uploading to root receipts folder.")
    return parent_folder_id


def upload_receipt(file_path: str, original_filename: str, name: str, item: str, date: str = "") -> dict:
    """
    Upload file to the person's subfolder inside the Fubon Braves Receipts folder.
    File is named "Name - Reimbursed Item.ext"
    Returns dict with 'id' and 'webViewLink'.
    """
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    if not folder_id:
        print("ERROR: DRIVE_FOLDER_ID not set in .env", file=sys.stderr)
        sys.exit(1)

    creds = get_google_creds()
    service = build("drive", "v3", credentials=creds)

    # Route to person's subfolder (e.g. Spencer/, Aven/, Wang/)
    target_folder_id = _get_subfolder_id(service, folder_id, name)

    # Detect MIME type
    ext = Path(original_filename).suffix.lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".heic": "image/heic",
    }
    mime_type = mime_map.get(ext, "application/octet-stream")

    # Build descriptive filename: "Spencer - Meal.pdf"
    drive_filename = f"{name} - {item}{ext}"

    file_metadata = {
        "name": drive_filename,
        "parents": [target_folder_id],
    }
    media = MediaFileUpload(file_path, mimetype=mime_type, resumable=False)

    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink",
    ).execute()

    print(f"Uploaded to Drive as '{drive_filename}': {uploaded.get('webViewLink')}")
    return uploaded
