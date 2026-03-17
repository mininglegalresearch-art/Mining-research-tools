"""
clean_narrative.py — Step 2 of the Audio-to-Storybook Pipeline

Purpose:  Use GPT-4o to transform the raw Whisper transcript into clean,
          warm narrative prose suitable for a children's picture book.

Required .env keys:
    OPENAI_API_KEY — OpenAI API key

Input:  .tmp/transcript_raw.txt — raw transcript from transcribe_audio.py
Output: .tmp/narrative_clean.txt — polished narrative text

Next step: run tools/generate_storyboard.py
"""

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
INPUT_FILE = TMP_DIR / "transcript_raw.txt"
OUTPUT_FILE = TMP_DIR / "narrative_clean.txt"

SYSTEM_PROMPT = (
    "You are a children's book editor. You will receive a raw audio transcript and must "
    "rewrite it as clear, warm, engaging narrative prose suitable for a children's picture "
    "book (ages 4–8). Fix transcription errors, remove filler words (um, uh, like, you know), "
    "smooth out sentence structure, and make the language simple, vivid, and joyful. "
    "Preserve all original story events and their order. "
    "Output only the cleaned narrative text — no commentary, no headings, no meta-text."
)


def main():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run tools/transcribe_audio.py first.")
        sys.exit(1)

    TMP_DIR.mkdir(parents=True, exist_ok=True)

    raw_text = INPUT_FILE.read_text(encoding="utf-8").strip()
    input_words = len(raw_text.split())

    print(f"Input:  {input_words} words from {INPUT_FILE.name}")
    print("  Sending to GPT-4o for narrative cleanup...")

    start = time.time()
    client = openai.OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model="gpt-4o",
        temperature=0.7,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": raw_text},
        ],
    )

    elapsed = time.time() - start
    narrative = response.choices[0].message.content.strip()

    OUTPUT_FILE.write_text(narrative, encoding="utf-8")

    output_words = len(narrative.split())
    print(f"  Done in {elapsed:.1f}s — {output_words} words (from {input_words} input words)")
    print(f"  Output written to: {OUTPUT_FILE}")
    print()
    print("Next step: run tools/generate_storyboard.py")


if __name__ == "__main__":
    main()
