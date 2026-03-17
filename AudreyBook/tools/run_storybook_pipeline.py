"""
run_storybook_pipeline.py — Full pipeline orchestrator

Purpose:  Run all steps of the Audio-to-Storybook pipeline in sequence.
          Each step runs as a subprocess. On any failure, execution stops
          with a clear error message pointing to the failing step.
          Completed steps support checkpoint/resume — re-running the full
          pipeline after a failure will skip already-finished work.

Usage:
    python tools/run_storybook_pipeline.py --input /path/to/audio.m4a

Steps:
    1.  transcribe_audio.py          — Whisper API transcription        → .tmp/transcript_raw.txt
    2.  clean_narrative.py           — GPT-4o narrative cleanup         → .tmp/narrative_clean.txt
    2b. analyze_story_style.py       — GPT-4o story→style profile       → .tmp/story_style_profile.json
    3.  generate_storyboard.py       — GPT-4o 15-scene storyboard       → .tmp/storyboard.json
    4.  generate_images.py           — DALL-E 3 image generation        → .tmp/images/scene_*.png
    4b. check_character_consistency  — GPT-4o cross-image consistency   → .tmp/character_registry.json
    5.  build_pdf.py                 — reportlab illustrated PDF         → .tmp/storybook.pdf
    6.  lulu_format_pdf.py           — Lulu 10"×8" spec PDFs            → .tmp/storybook_lulu_*.pdf
    7.  upload_to_lulu.py            — Drive upload + Lulu validation   → .tmp/lulu_validation.json
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
TMP_DIR = PROJECT_DIR / ".tmp"

SUPPORTED_FORMATS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".webm", ".mp4"}


def main():
    parser = argparse.ArgumentParser(description="Audio-to-Storybook Pipeline Orchestrator")
    parser.add_argument("--input", required=True, help="Path to the input audio file")
    args = parser.parse_args()

    audio_path = Path(args.input).resolve()
    if not audio_path.exists():
        print(f"ERROR: Audio file not found: {audio_path}")
        sys.exit(1)

    if audio_path.suffix.lower() not in SUPPORTED_FORMATS:
        print(f"ERROR: Unsupported audio format '{audio_path.suffix}'.")
        print(f"  Supported: {', '.join(sorted(SUPPORTED_FORMATS))}")
        sys.exit(1)

    steps = [
        {
            "name": "Transcribe Audio",
            "cmd": [sys.executable, str(SCRIPT_DIR / "transcribe_audio.py"), "--input", str(audio_path)],
        },
        {
            "name": "Clean Narrative",
            "cmd": [sys.executable, str(SCRIPT_DIR / "clean_narrative.py")],
        },
        {
            "name": "Analyze Story Style",
            "cmd": [sys.executable, str(SCRIPT_DIR / "analyze_story_style.py")],
        },
        {
            "name": "Generate Storyboard",
            "cmd": [sys.executable, str(SCRIPT_DIR / "generate_storyboard.py")],
        },
        {
            "name": "Generate Images",
            "cmd": [sys.executable, str(SCRIPT_DIR / "generate_images.py")],
        },
        {
            "name": "Check Character Consistency",
            "cmd": [sys.executable, str(SCRIPT_DIR / "check_character_consistency.py")],
        },
        {
            "name": "Build PDF",
            "cmd": [sys.executable, str(SCRIPT_DIR / "build_pdf.py")],
        },
        {
            "name": "Format for Lulu",
            "cmd": [sys.executable, str(SCRIPT_DIR / "lulu_format_pdf.py")],
        },
        {
            "name": "Upload and Validate Lulu",
            "cmd": [sys.executable, str(SCRIPT_DIR / "upload_to_lulu.py")],
        },
    ]

    print("=" * 60)
    print("  Audio-to-Storybook Pipeline")
    print(f"  Input: {audio_path.name}")
    print("=" * 60)
    print()

    overall_start = time.time()

    for i, step in enumerate(steps, 1):
        print(f"=== Step {i}/{len(steps)}: {step['name']} ===")
        step_start = time.time()

        try:
            subprocess.run(step["cmd"], check=True)
        except subprocess.CalledProcessError as e:
            print()
            print(f"ERROR: Step {i}/{len(steps)} failed — {step['name']} (exit code {e.returncode})")
            print("  Fix the error above and re-run. Completed steps will resume from checkpoint.")
            sys.exit(1)

        step_elapsed = time.time() - step_start
        print(f"  Step {i} complete in {step_elapsed:.1f}s")
        print()

    total_elapsed = time.time() - overall_start
    output_pdf         = TMP_DIR / "storybook.pdf"
    lulu_interior_pdf  = TMP_DIR / "storybook_lulu_interior.pdf"
    lulu_cover_pdf     = TMP_DIR / "storybook_lulu_cover.pdf"
    lulu_validation    = TMP_DIR / "lulu_validation.json"

    print("=" * 60)
    print(f"  Pipeline complete in {total_elapsed:.1f}s")
    print(f"  Preview PDF:      {output_pdf}")
    print(f"  Lulu interior:    {lulu_interior_pdf}")
    print(f"  Lulu cover:       {lulu_cover_pdf}")
    print(f"  Lulu validation:  {lulu_validation}")
    print("=" * 60)


if __name__ == "__main__":
    main()
