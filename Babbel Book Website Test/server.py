"""
server.py — Babbel Books backend

Endpoints:
  POST /signup   — email waitlist capture → Google Sheets
  POST /process  — audio upload + child profile → kick off storybook pipeline
  GET  /health   — liveness check

POST /process payload (multipart/form-data):
  audio    — audio file (mp3, m4a, wav, etc.)
  profile  — JSON string with child profile:
             { name, age, gender, friends[], toys[] }

On receipt, /process:
  1. Validates the profile
  2. Saves the audio file to the AudreyBook .tmp/ folder
  3. Writes child_profile.json to .tmp/
  4. Spawns the pipeline as a background subprocess
  5. Returns { job_id, status: "started" }

Setup:
  1. pip install flask flask-cors google-auth google-auth-oauthlib google-api-python-client python-dotenv
  2. Set BABBEL_SIGNUPS_SHEET_ID in .env
  3. Run: python server.py

The server runs on http://localhost:5001
"""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ── Config ──────────────────────────────────────────────────────────────────
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

# AudreyBook pipeline paths (sibling directory)
AUDREYBOOK_DIR = Path(__file__).parent.parent / "AudreyBook"
PIPELINE_SCRIPT = AUDREYBOOK_DIR / "tools" / "run_storybook_pipeline.py"
TMP_DIR = AUDREYBOOK_DIR / ".tmp"
AUDIO_UPLOAD_DIR = TMP_DIR / "uploads"

SUPPORTED_AUDIO = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".webm", ".mp4"}

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = os.getenv("BABBEL_SIGNUPS_SHEET_ID")

# credentials.json lives in the project root (shared with other pipelines)
CREDENTIALS_FILE = Path(__file__).parent.parent / "credentials.json"
TOKEN_FILE = Path(__file__).parent.parent / "token.json"

HEADERS = ["Date Submitted", "Name", "Email", "Child's Age"]

# ── Google Sheets auth ───────────────────────────────────────────────────────
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
                    f"credentials.json not found at {CREDENTIALS_FILE}. "
                    "Download it from Google Cloud Console and place it in the project root."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def get_sheets_service():
    return build("sheets", "v4", credentials=authenticate())


def ensure_header_row(service):
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range="A1:D1"
    ).execute()
    if not result.get("values"):
        service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range="A1:D1",
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        ).execute()


def append_row(service, name, email, child_age):
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [date_str, name or "", email, child_age or ""]
    service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range="A:D",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


# ── Flask app ────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)  # allow requests from the local HTML file

# Authenticate and warm up the Sheets connection on startup
try:
    _service = get_sheets_service()
    ensure_header_row(_service)
    print(f"✓ Connected to Google Sheet: {SHEET_ID}")
except Exception as e:
    _service = None
    print(f"⚠ Could not connect to Google Sheets on startup: {e}")
    print("  Make sure BABBEL_SIGNUPS_SHEET_ID is set in .env and credentials.json exists.")


@app.route("/signup", methods=["POST"])
def signup():
    global _service
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    child_age = (data.get("child_age") or "").strip()

    if not email:
        return jsonify({"error": "email is required"}), 400

    if not SHEET_ID:
        return jsonify({"error": "BABBEL_SIGNUPS_SHEET_ID not set in .env"}), 500

    try:
        if _service is None:
            _service = get_sheets_service()
            ensure_header_row(_service)
        append_row(_service, name, email, child_age)
        print(f"  ✓ Saved: {email} | {name} | {child_age}")
        return jsonify({"success": True}), 200
    except HttpError as e:
        print(f"  ✗ Sheets error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/process", methods=["POST"])
def process():
    """
    Accept audio + child profile, save both, and launch the pipeline subprocess.
    Returns { job_id, status: "started" } on success.
    """
    # ── Validate audio file ──────────────────────────────────────────────────
    if "audio" not in request.files:
        return jsonify({"error": "audio file is required"}), 400

    audio_file = request.files["audio"]
    suffix = Path(audio_file.filename).suffix.lower() if audio_file.filename else ""
    if not suffix or suffix not in SUPPORTED_AUDIO:
        return jsonify({
            "error": f"Unsupported audio format '{suffix}'. Supported: {', '.join(sorted(SUPPORTED_AUDIO))}"
        }), 400

    # ── Validate child profile ───────────────────────────────────────────────
    profile_raw = request.form.get("profile", "")
    if not profile_raw:
        return jsonify({"error": "profile JSON is required"}), 400

    try:
        profile_data = json.loads(profile_raw)
    except json.JSONDecodeError as e:
        return jsonify({"error": f"profile is not valid JSON: {e}"}), 400

    if not profile_data.get("name"):
        return jsonify({"error": "profile.name is required"}), 400
    if not profile_data.get("age"):
        return jsonify({"error": "profile.age is required"}), 400

    # Normalise list fields (comma-separated strings → lists)
    for field_name in ("friends", "toys"):
        val = profile_data.get(field_name, [])
        if isinstance(val, str):
            profile_data[field_name] = [x.strip() for x in val.split(",") if x.strip()]

    # ── Save audio file ──────────────────────────────────────────────────────
    AUDIO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    job_id = str(uuid.uuid4())[:8]
    audio_path = AUDIO_UPLOAD_DIR / f"{job_id}{suffix}"
    audio_file.save(str(audio_path))

    # ── Save child profile ───────────────────────────────────────────────────
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = TMP_DIR / "child_profile.json"
    profile_path.write_text(json.dumps(profile_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Launch pipeline subprocess ───────────────────────────────────────────
    if not PIPELINE_SCRIPT.exists():
        return jsonify({"error": f"Pipeline script not found at {PIPELINE_SCRIPT}"}), 500

    log_path = TMP_DIR / f"pipeline_{job_id}.log"

    try:
        with open(log_path, "w") as log_f:
            subprocess.Popen(
                [
                    sys.executable,
                    str(PIPELINE_SCRIPT),
                    "--input", str(audio_path),
                    "--profile", json.dumps(profile_data),
                ],
                stdout=log_f,
                stderr=log_f,
                cwd=str(AUDREYBOOK_DIR),
            )
    except Exception as e:
        return jsonify({"error": f"Failed to start pipeline: {e}"}), 500

    print(f"  ✓ Pipeline started | job={job_id} | child={profile_data['name']} age={profile_data['age']}")
    print(f"    Audio: {audio_path.name}")
    print(f"    Log:   {log_path.name}")

    return jsonify({
        "job_id": job_id,
        "status": "started",
        "child": profile_data["name"],
        "log": str(log_path),
    }), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    print("\nBabbel Books server")
    print("───────────────────────────────────────")
    print("  POST /signup   — email waitlist capture")
    print("  POST /process  — audio + profile → pipeline")
    print("  GET  /health   — liveness check")
    print()
    print("Listening on http://localhost:5001")
    print("Ctrl+C to stop\n")
    app.run(port=5001, debug=False)
