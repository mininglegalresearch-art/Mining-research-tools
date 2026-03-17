"""
upload_to_lulu.py — Step 9 of the Audio-to-Storybook Pipeline

Purpose:  Upload the Lulu-formatted PDFs to Google Drive (for public hosting),
          then submit them to the Lulu API for print validation.

Steps:
    A. Authenticate with Google Drive (OAuth2 — browser prompt on first run)
       Uses a separate token_drive.json to avoid conflicts with the Sheets token.
    B. Upload interior + cover PDFs; set "anyone with link" read permission
    C. Authenticate with Lulu API (OAuth2 client_credentials)
    D. Submit interior to POST /interior-validations/
       Submit cover    to POST /cover-validations/
    E. Poll until each reaches a terminal status
       Interior: VALIDATED  or ERROR
       Cover:    NORMALIZED or ERROR
    F. Save results to .tmp/lulu_validation.json; exit 1 on any failure

Required .env keys:
    LULU_CLIENT_KEY     — from https://developers.lulu.com/user-profile/api-keys
    LULU_CLIENT_SECRET
    LULU_ENVIRONMENT    — "sandbox" (default) or "production"

Required files:
    credentials.json   (Google OAuth client secret — project root; gitignored)

Input:  .tmp/storybook_lulu_interior.pdf
        .tmp/storybook_lulu_cover.pdf

Output: .tmp/lulu_validation.json  — full validation results
"""

import base64
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
ROOT_DIR = PROJECT_DIR.parent         # project root (where credentials.json lives)
TMP_DIR = PROJECT_DIR / ".tmp"
INTERIOR_PDF = TMP_DIR / "storybook_lulu_interior.pdf"
COVER_PDF    = TMP_DIR / "storybook_lulu_cover.pdf"
VALIDATION_OUTPUT = TMP_DIR / "lulu_validation.json"

CREDENTIALS_FILE = ROOT_DIR / "credentials.json"
TOKEN_FILE = ROOT_DIR / "token_drive.json"   # separate from token.json (Sheets)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# ---------------------------------------------------------------------------
# Lulu API configuration
# ---------------------------------------------------------------------------
LULU_CLIENT_KEY    = os.getenv("LULU_CLIENT_KEY", "")
LULU_CLIENT_SECRET = os.getenv("LULU_CLIENT_SECRET", "")
LULU_ENVIRONMENT   = os.getenv("LULU_ENVIRONMENT", "sandbox").lower()

if LULU_ENVIRONMENT == "production":
    LULU_BASE_URL  = "https://api.lulu.com"
    LULU_AUTH_URL  = "https://api.lulu.com/auth/realms/glasstree/protocol/openid-connect/token"
else:
    LULU_BASE_URL  = "https://api.sandbox.lulu.com"
    LULU_AUTH_URL  = "https://api.sandbox.lulu.com/auth/realms/glasstree/protocol/openid-connect/token"

POD_PACKAGE_ID     = "1000X0800FCSTDPB080CW444GXX"
INTERIOR_PAGE_COUNT = 24   # matches MIN_PAGES in lulu_format_pdf.py

POLL_INTERVAL_SEC = 10
POLL_MAX_ATTEMPTS = 60     # 10 min timeout


# ===========================================================================
# Step A+B — Google Drive upload
# ===========================================================================

def authenticate_drive() -> Credentials:
    """OAuth2 for Drive (drive.file scope). Uses token_drive.json — separate from Sheets token."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), DRIVE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"credentials.json not found at {CREDENTIALS_FILE}\n"
                    "Download it from Google Cloud Console:\n"
                    "  APIs & Services > Credentials > OAuth 2.0 Client IDs\n"
                    "and place it in the project root."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), DRIVE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as fh:
            fh.write(creds.to_json())
        print(f"  Drive token saved → {TOKEN_FILE.name}")

    return creds


def upload_pdf_to_drive(service, pdf_path: Path, description: str) -> dict:
    """
    Upload a PDF to Google Drive and set it to public read.
    Returns {"file_id": str, "download_url": str, "name": str}.
    """
    file_name = pdf_path.name
    print(f"  Uploading {description}: {file_name}  ({pdf_path.stat().st_size // 1024} KB)...")

    media = MediaFileUpload(str(pdf_path), mimetype="application/pdf", resumable=True)
    file_meta = {"name": file_name, "description": description}

    uploaded = service.files().create(
        body=file_meta,
        media_body=media,
        fields="id, name",
    ).execute()

    file_id = uploaded["id"]

    # Set anyone-with-link read permission
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    print(f"    → {download_url}")

    return {"file_id": file_id, "download_url": download_url, "name": file_name}


def upload_pdfs_to_drive() -> tuple[str, str]:
    """
    Authenticate with Drive and upload both PDFs.
    Returns (interior_download_url, cover_download_url).
    """
    print("Authenticating with Google Drive...")
    creds = authenticate_drive()
    service = build("drive", "v3", credentials=creds)
    print("  Authenticated.")

    print("Uploading PDFs to Google Drive...")
    interior_info = upload_pdf_to_drive(service, INTERIOR_PDF, "Lulu Interior PDF")
    cover_info    = upload_pdf_to_drive(service, COVER_PDF,    "Lulu Cover PDF")

    print(f"  Upload complete.")
    return interior_info["download_url"], cover_info["download_url"]


# ===========================================================================
# Step C — Lulu authentication
# ===========================================================================

def get_lulu_token() -> str:
    """
    Exchange client credentials for a Lulu bearer access token.
    Uses HTTP Basic auth: base64(client_key:client_secret).
    """
    if not LULU_CLIENT_KEY or not LULU_CLIENT_SECRET:
        raise ValueError(
            "LULU_CLIENT_KEY and LULU_CLIENT_SECRET must be set in .env\n"
            "Get credentials at: https://developers.lulu.com/user-profile/api-keys"
        )

    credentials_b64 = base64.b64encode(
        f"{LULU_CLIENT_KEY}:{LULU_CLIENT_SECRET}".encode()
    ).decode()

    print(f"Authenticating with Lulu API ({LULU_ENVIRONMENT})...")
    resp = requests.post(
        LULU_AUTH_URL,
        headers={
            "Authorization": f"Basic {credentials_b64}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials"},
        timeout=30,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Lulu auth failed: {resp.status_code} — {resp.text[:300]}"
        )

    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(f"Lulu auth: no access_token in response: {resp.text[:300]}")

    print("  Lulu token obtained.")
    return token


# ===========================================================================
# Step D — Submit validations
# ===========================================================================

def submit_interior_validation(token: str, source_url: str) -> str:
    """POST /interior-validations/ — returns validation job ID."""
    url = f"{LULU_BASE_URL}/interior-validations/"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"source_url": source_url},
        timeout=30,
    )
    if resp.status_code not in (200, 201, 202):
        raise RuntimeError(
            f"Interior validation submission failed: {resp.status_code} — {resp.text[:400]}"
        )
    data = resp.json()
    job_id = data.get("id") or data.get("job_id") or str(data)
    print(f"  Interior validation submitted — ID: {job_id}")
    return job_id, data


def submit_cover_validation(token: str, source_url: str) -> str:
    """POST /cover-validations/ — returns validation job ID."""
    url = f"{LULU_BASE_URL}/cover-validations/"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "source_url": source_url,
            "pod_package_id": POD_PACKAGE_ID,
            "interior_page_count": INTERIOR_PAGE_COUNT,
        },
        timeout=30,
    )
    if resp.status_code not in (200, 201, 202):
        raise RuntimeError(
            f"Cover validation submission failed: {resp.status_code} — {resp.text[:400]}"
        )
    data = resp.json()
    job_id = data.get("id") or data.get("job_id") or str(data)
    print(f"  Cover validation submitted — ID: {job_id}")
    return job_id, data


# ===========================================================================
# Step E — Poll for results
# ===========================================================================

def poll_interior_validation(token: str, job_id: str) -> dict:
    """
    Poll GET /interior-validations/{id}/ until terminal status.
    Terminal: VALIDATED or ERROR (or any unrecognized terminal state).
    """
    url = f"{LULU_BASE_URL}/interior-validations/{job_id}/"
    print(f"  Polling interior validation {job_id}...")

    for attempt in range(1, POLL_MAX_ATTEMPTS + 1):
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Interior poll error: {resp.status_code} — {resp.text[:300]}"
            )
        data = resp.json()
        status = (data.get("status") or data.get("state") or "UNKNOWN").upper()

        print(f"    [{attempt:02d}/{POLL_MAX_ATTEMPTS}] Status: {status}")

        if status == "VALIDATED":
            print("    PASSED — interior validated successfully.")
            return {"passed": True, "status": status, "data": data}
        if status == "ERROR" or "error" in status.lower():
            errors = data.get("errors") or data.get("messages") or []
            print(f"    FAILED — interior validation errors: {errors}")
            return {"passed": False, "status": status, "errors": errors, "data": data}

        time.sleep(POLL_INTERVAL_SEC)

    raise RuntimeError(
        f"Interior validation timed out after {POLL_MAX_ATTEMPTS * POLL_INTERVAL_SEC}s"
    )


def poll_cover_validation(token: str, job_id: str) -> dict:
    """
    Poll GET /cover-validations/{id}/ until terminal status.
    Terminal: NORMALIZED or ERROR.
    """
    url = f"{LULU_BASE_URL}/cover-validations/{job_id}/"
    print(f"  Polling cover validation {job_id}...")

    for attempt in range(1, POLL_MAX_ATTEMPTS + 1):
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Cover poll error: {resp.status_code} — {resp.text[:300]}"
            )
        data = resp.json()
        status = (data.get("status") or data.get("state") or "UNKNOWN").upper()

        print(f"    [{attempt:02d}/{POLL_MAX_ATTEMPTS}] Status: {status}")

        if status == "NORMALIZED":
            print("    PASSED — cover normalized successfully.")
            return {"passed": True, "status": status, "data": data}
        if status == "ERROR" or "error" in status.lower():
            errors = data.get("errors") or data.get("messages") or []
            print(f"    FAILED — cover validation errors: {errors}")
            return {"passed": False, "status": status, "errors": errors, "data": data}

        time.sleep(POLL_INTERVAL_SEC)

    raise RuntimeError(
        f"Cover validation timed out after {POLL_MAX_ATTEMPTS * POLL_INTERVAL_SEC}s"
    )


# ===========================================================================
# Entry point
# ===========================================================================

def main():
    # --- Validate inputs ---
    missing = []
    if not INTERIOR_PDF.exists():
        missing.append(str(INTERIOR_PDF))
    if not COVER_PDF.exists():
        missing.append(str(COVER_PDF))
    if missing:
        print("ERROR: Lulu PDFs not found. Run lulu_format_pdf.py first.")
        for m in missing:
            print(f"  Missing: {m}")
        sys.exit(1)

    print()
    print(f"=== Lulu Upload + Validation  ({LULU_ENVIRONMENT.upper()}) ===")
    print()

    # --- Step A+B: Upload to Drive ---
    interior_url, cover_url = upload_pdfs_to_drive()
    print()

    # --- Step C: Lulu auth ---
    try:
        lulu_token = get_lulu_token()
    except (ValueError, RuntimeError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print()

    # --- Step D: Submit validations ---
    print("Submitting validations to Lulu...")
    try:
        interior_job_id, _interior_submit = submit_interior_validation(lulu_token, interior_url)
        cover_job_id,    _cover_submit    = submit_cover_validation(lulu_token, cover_url)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print()

    # --- Step E: Poll ---
    print("Polling validation results...")
    try:
        interior_result = poll_interior_validation(lulu_token, interior_job_id)
        print()
        cover_result = poll_cover_validation(lulu_token, cover_job_id)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # --- Save results ---
    results = {
        "environment": LULU_ENVIRONMENT,
        "pod_package_id": POD_PACKAGE_ID,
        "interior": {
            "source_url": interior_url,
            "job_id": interior_job_id,
            **interior_result,
        },
        "cover": {
            "source_url": cover_url,
            "job_id": cover_job_id,
            **cover_result,
        },
    }

    VALIDATION_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(VALIDATION_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print()
    print("=== Validation Summary ===")
    interior_status = "PASSED" if interior_result["passed"] else "FAILED"
    cover_status    = "PASSED" if cover_result["passed"]    else "FAILED"
    print(f"  Interior: {interior_status}  ({interior_result['status']})")
    print(f"  Cover:    {cover_status}  ({cover_result['status']})")
    print(f"  Results saved → {VALIDATION_OUTPUT}")

    if not interior_result["passed"] or not cover_result["passed"]:
        print()
        print("  One or more validations FAILED. See lulu_validation.json for details.")
        sys.exit(1)

    print()
    print("Both files validated successfully.")
    print("Next: log in to your Lulu account to review and place a print order.")


if __name__ == "__main__":
    main()
