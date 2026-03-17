"""
tools/push_to_google_sheets.py

Reads .tmp/companies_with_email.json and writes all enriched mining company
records to a Google Sheet. Idempotent — skips rows whose ticker already exists
in the sheet.

Required .env keys:
    GOOGLE_SHEETS_ID

Required files:
    credentials.json  (OAuth client secret, downloaded from Google Cloud Console)

Outputs:
    Google Sheet with 21 columns (see HEADERS below)
    token.json  (written automatically on first OAuth authorization)
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = os.getenv("GOOGLE_SHEETS_ID")
INPUT_FILE = Path(".tmp/companies_with_email.json")
CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path("token.json")
BATCH_SIZE = 50

HEADERS = [
    "Company Name",
    "Ticker",
    "Exchange",
    "CEO Name",
    "General Counsel Name",
    "GC Title",
    "GC Email",
    "Email Confidence",
    "LinkedIn Search URL",
    "Jurisdictions",
    "Total Revenue (USD)",
    "Revenue Year",
    "Tons Ore Processed",
    "Major Projects",
    "Project Countries",
    "Market Cap (USD)",
    "Company Website",
    "CIK (EDGAR)",
    "Data Sources",
    "Last Updated",
    "Notes / Flags",
]


def authenticate():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    "credentials.json not found. Download it from Google Cloud Console "
                    "(APIs & Services > Credentials > OAuth 2.0 Client IDs) and place "
                    "it in the project root."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def get_existing_tickers(service, sheet_id):
    """Read column B (Ticker) from the sheet and return a set of existing tickers."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range="B:B"
        ).execute()
        values = result.get("values", [])
        # Skip header row, flatten to set
        return {row[0].strip() for row in values[1:] if row}
    except HttpError:
        return set()


def ensure_header_row(service, sheet_id):
    """Write the header row if the sheet is empty."""
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range="A1:A1"
    ).execute()
    if not result.get("values"):
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range="A1",
            valueInputOption="USER_ENTERED",
            body={"values": [HEADERS]}
        ).execute()
        print("Header row written.")


def record_to_row(r):
    """Map a company record dict to a list of 21 cell values."""
    return [
        r.get("name") or r.get("long_name") or "",
        r.get("ticker") or "",
        r.get("exchange") or r.get("exchange_yf") or "",
        r.get("ceo_name") or "",
        r.get("gc_name") or "",
        r.get("gc_title") or "",
        r.get("gc_email") or "",
        r.get("email_confidence") or "",
        r.get("linkedin_search_url") or "",
        r.get("jurisdictions") or "",
        r.get("total_revenue") or "",
        r.get("revenue_year") or "",
        r.get("tons_ore_processed") or "",
        "; ".join(r.get("projects") or []),
        "; ".join(r.get("project_countries") or []),
        r.get("market_cap") or "",
        r.get("website") or "",
        r.get("cik") or "",
        ", ".join(r.get("data_sources") or []),
        datetime.utcnow().isoformat(),
        "; ".join(filter(None, [
            "gc_search_needed" if r.get("gc_search_needed") else "",
            "website_unreachable" if r.get("website_unreachable") else "",
            "no_active_ticker" if r.get("no_active_ticker") else "",
            "yfinance_error" if r.get("yfinance_error") else "",
            r.get("notes") or "",
        ])),
    ]


def append_rows(service, sheet_id, rows):
    """Append rows in batches of BATCH_SIZE."""
    total = len(rows)
    added = 0
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range="A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": batch},
        ).execute()
        added += len(batch)
        print(f"  Written {added}/{total} rows...")
        if i + BATCH_SIZE < total:
            time.sleep(1)  # respect 60 writes/min rate limit
    return added


def main():
    if not SHEET_ID:
        print("ERROR: GOOGLE_SHEETS_ID is not set in .env")
        return

    if not INPUT_FILE.exists():
        print(f"ERROR: Input file not found: {INPUT_FILE}")
        print("Run the pipeline tools first to generate company data.")
        return

    with open(INPUT_FILE) as f:
        companies = json.load(f)

    print(f"Loaded {len(companies)} company records from {INPUT_FILE}")

    creds = authenticate()
    service = build("sheets", "v4", credentials=creds)

    ensure_header_row(service, SHEET_ID)
    existing_tickers = get_existing_tickers(service, SHEET_ID)
    print(f"Sheet already has {len(existing_tickers)} tickers. Skipping duplicates.")

    new_rows = []
    skipped = 0
    for r in companies:
        ticker = (r.get("ticker") or "").strip()
        if ticker and ticker in existing_tickers:
            skipped += 1
            continue
        new_rows.append(record_to_row(r))

    if not new_rows:
        print(f"No new companies to add. Skipped {skipped} duplicates.")
        return

    print(f"Appending {len(new_rows)} new rows ({skipped} duplicates skipped)...")
    added = append_rows(service, SHEET_ID, new_rows)
    print(f"\nDone. {added} rows added to Google Sheet.")
    print(f"Sheet URL: https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")


if __name__ == "__main__":
    main()
