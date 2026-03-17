"""
run_news_pipeline.py — Mining News Digest Pipeline Orchestrator

Runs all four pipeline steps in sequence:
  1. fetch_mining_news.py       — Fetch articles from 5 RSS feeds  → .tmp/news_articles.json
  2. summarize_news.py          — GPT-4o digest                    → .tmp/news_summary.json
  3. find_outreach_targets.py   — Dispute target ID + contacts     → .tmp/outreach_targets.json
  4. send_email_digest.py       — Gmail SMTP delivery              → email sent

Usage:
    python "Mining News Scrapper/tools/run_news_pipeline.py"
    python "Mining News Scrapper/tools/run_news_pipeline.py" --skip-fetch
    python "Mining News Scrapper/tools/run_news_pipeline.py" --dry-run

Flags:
    --skip-fetch   Reuse existing .tmp/news_articles.json (skip Step 1)
                   Useful for re-running without re-fetching.
    --dry-run      Fetch + summarize + find targets, but write digest_preview.html
                   instead of sending. Open in browser to review before live send.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
TMP_DIR = PROJECT_DIR / ".tmp"


def main():
    parser = argparse.ArgumentParser(description="Mining News Digest Pipeline")
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Skip fetch step and reuse existing news_articles.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Full pipeline but write digest_preview.html instead of sending email",
    )
    args = parser.parse_args()

    # Build step list
    steps = []

    if not args.skip_fetch:
        steps.append({
            "name": "Fetch Mining News",
            "cmd": [sys.executable, str(SCRIPT_DIR / "fetch_mining_news.py")],
        })
    else:
        articles_file = TMP_DIR / "news_articles.json"
        if not articles_file.exists():
            print(f"ERROR: --skip-fetch specified but {articles_file} does not exist.")
            print("  Run without --skip-fetch to fetch fresh articles.")
            sys.exit(1)
        print(f"  --skip-fetch: reusing {articles_file}")

    steps.append({
        "name": "Summarize with GPT-4o",
        "cmd": [sys.executable, str(SCRIPT_DIR / "summarize_news.py")],
    })

    steps.append({
        "name": "Find Outreach Targets",
        "cmd": [sys.executable, str(SCRIPT_DIR / "find_outreach_targets.py")],
    })

    send_cmd = [sys.executable, str(SCRIPT_DIR / "send_email_digest.py")]
    if args.dry_run:
        send_cmd.append("--dry-run")
    steps.append({
        "name": "Send Email Digest" if not args.dry_run else "Build Email Preview (dry run)",
        "cmd": send_cmd,
    })

    # Header
    print("=" * 60)
    print("  Mining News Digest Pipeline")
    if args.dry_run:
        print("  Mode: DRY RUN — email will NOT be sent")
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
            print("  Fix the error above and re-run.")
            print("  Tip: use --skip-fetch to reuse already-fetched articles.")
            sys.exit(1)

        step_elapsed = time.time() - step_start
        print(f"  Step {i} complete in {step_elapsed:.1f}s")
        print()

    total_elapsed = time.time() - overall_start

    print("=" * 60)
    print(f"  Pipeline complete in {total_elapsed:.1f}s")
    if args.dry_run:
        print(f"  Preview saved to: {TMP_DIR / 'digest_preview_vN.html'} (check .tmp/ for latest version)")
        print("  Open the preview in a browser, then run without --dry-run to send.")
    else:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        recipient = os.getenv("NEWS_RECIPIENT_EMAIL", "mininglegalresearch@gmail.com")
        print(f"  Email sent to: {recipient}")
        print(f"  Articles:       {TMP_DIR / 'news_articles.json'}")
        print(f"  Summary:        {TMP_DIR / 'news_summary.json'}")
        print(f"  Outreach:       {TMP_DIR / 'outreach_targets.json'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
