"""
google_auth.py
--------------
Loads Google OAuth credentials from the GOOGLE_TOKEN_JSON environment variable
(the contents of token.json as a single-line JSON string).

To set up:
1. Run the app locally once to generate token.json (already done)
2. Copy token.json contents into GOOGLE_TOKEN_JSON env var (single line)
3. The token auto-refreshes in memory — no file writing needed on the server
"""

import json
import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]


def get_google_creds() -> Credentials:
    """Load and refresh OAuth credentials from GOOGLE_TOKEN_JSON env var."""
    token_json = os.getenv("GOOGLE_TOKEN_JSON")
    if not token_json:
        print("ERROR: GOOGLE_TOKEN_JSON not set in .env", file=sys.stderr)
        sys.exit(1)
    try:
        token_data = json.loads(token_json)
    except json.JSONDecodeError as e:
        print(f"ERROR: GOOGLE_TOKEN_JSON is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds
