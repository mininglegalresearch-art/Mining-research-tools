"""
transcribe_audio.py — Step 1 of the Audio-to-Storybook Pipeline

Purpose:  Transcribe an audio file using the OpenAI Whisper API (whisper-1).

Required .env keys:
    OPENAI_API_KEY — OpenAI API key

Input:  audio file path via --input CLI argument
        Supported: .mp3, .m4a, .wav, .flac, .ogg, .webm, .mp4
        Maximum file size: 25 MB (Whisper API limit)

Output: .tmp/transcript_raw.txt — raw transcript text

Next step: run tools/clean_narrative.py
"""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import openai

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
TMP_DIR = PROJECT_DIR / ".tmp"
OUTPUT_FILE = TMP_DIR / "transcript_raw.txt"

SUPPORTED_FORMATS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".webm", ".mp4"}
MAX_FILE_SIZE_MB = 25


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio using OpenAI Whisper API")
    parser.add_argument("--input", required=True, help="Path to audio file")
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    audio_path = Path(args.input)
    if not audio_path.exists():
        print(f"ERROR: Audio file not found: {audio_path}")
        sys.exit(1)

    suffix = audio_path.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        print(f"ERROR: Unsupported format '{suffix}'. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}")
        sys.exit(1)

    file_size_mb = audio_path.stat().st_size / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        print(f"ERROR: File is {file_size_mb:.1f} MB — exceeds Whisper API limit of {MAX_FILE_SIZE_MB} MB.")
        print("  Tip: split the file with ffmpeg:")
        print("  ffmpeg -i input.m4a -f segment -segment_time 600 -c copy part%02d.m4a")
        sys.exit(1)

    TMP_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Transcribing: {audio_path.name} ({file_size_mb:.1f} MB)")
    print("  Sending to OpenAI Whisper API (whisper-1)...")

    start = time.time()
    client = openai.OpenAI(api_key=api_key)

    with open(audio_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="text",
        )

    elapsed = time.time() - start

    OUTPUT_FILE.write_text(transcript, encoding="utf-8")

    word_count = len(transcript.split())
    char_count = len(transcript)
    print(f"  Done in {elapsed:.1f}s — {word_count} words / {char_count} characters")
    print(f"  Output written to: {OUTPUT_FILE}")
    print()
    print("Next step: run tools/clean_narrative.py")


if __name__ == "__main__":
    main()
