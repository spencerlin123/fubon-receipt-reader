"""
reauth.py
---------
One-time script to regenerate Google OAuth token.
Run this locally when GOOGLE_TOKEN_JSON expires.

Usage:
    python reauth.py

Then copy the printed JSON string into GOOGLE_TOKEN_JSON in Railway's env vars.
"""

import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]

flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

token_data = json.loads(creds.to_json())
single_line = json.dumps(token_data)

# Save to token.json for reference
Path("token.json").write_text(single_line)

print("\n" + "="*60)
print("Copy the line below into GOOGLE_TOKEN_JSON on Railway:")
print("="*60)
print(single_line)
