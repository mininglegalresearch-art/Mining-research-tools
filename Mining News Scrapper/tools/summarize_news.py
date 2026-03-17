"""
tools/summarize_news.py

Reads news_articles.json and uses GPT-4o to produce a structured weekly digest:
  - Executive Summary: 1-2 paragraphs (150-250 words) of the top developments
  - Source Breakdown: 2-3 bullet points per publication

Input:   .tmp/news_articles.json
Output:  .tmp/news_summary.json
"""

import json
import os
import re
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError, APITimeoutError

load_dotenv()

PROJECT_DIR = Path(__file__).parent.parent
TMP_DIR = PROJECT_DIR / ".tmp"
INPUT_FILE = TMP_DIR / "news_articles.json"
OUTPUT_FILE = TMP_DIR / "news_summary.json"

MAX_PROMPT_CHARS = 60_000   # well within GPT-4o's 128K context
RATE_LIMIT_SLEEP = 60       # seconds to wait on 429

SOURCE_ORDER = [
    "Mining.com",
    "The Northern Miner",
    "Mining Journal",
    "Mining Magazine",
    "Mining Weekly",
]

SYSTEM_PROMPT = """You are an expert mining industry analyst creating a concise weekly digest \
for a mining law research team. Be factual, precise, and use industry terminology. \
Focus on: company deals, M&A activity, regulatory changes, commodity prices, project \
updates, and legal/ESG developments. Avoid generic filler sentences."""


def build_user_prompt(articles_by_source):
    """Build the structured prompt for GPT-4o."""
    lines = []
    lines.append(
        "Below are mining news articles from the past 7 days, grouped by publication.\n"
        "Create a structured digest with two sections:\n\n"
        "SECTION 1 — EXECUTIVE SUMMARY\n"
        "Write 1-2 paragraphs (150-250 words total) highlighting the 3-5 most significant "
        "developments across all sources this week. Be specific — name companies, commodities, "
        "and dollar figures where available.\n\n"
        "SECTION 2 — SOURCE BREAKDOWN\n"
        "For each publication listed below, write 2-3 bullet points summarizing the key stories. "
        "If a source has no articles this week, write exactly: 'No articles this week.'\n"
        "Use this exact format:\n\n"
        "## Executive Summary\n\n"
        "[your 1-2 paragraphs here]\n\n"
        "## Source Breakdown\n\n"
        "### Mining.com\n- bullet\n- bullet\n\n"
        "### The Northern Miner\n- bullet\n\n"
        "(continue for all 5 sources)\n\n"
        "---\n\nARTICLE DATA:\n"
    )

    total_chars = sum(len(l) for l in lines)

    for source_name in SOURCE_ORDER:
        source_articles = articles_by_source.get(source_name, [])
        block = f"\n### {source_name}\n"
        if not source_articles:
            block += "(No articles retrieved this week)\n"
        else:
            for i, art in enumerate(source_articles, 1):
                paywall_note = " [paywalled — headline only]" if art.get("paywall") else ""
                snippet = art.get("snippet", "").strip()
                entry = (
                    f"{i}. {art['title']}{paywall_note}\n"
                    f"   URL: {art.get('url', '')}\n"
                )
                if snippet:
                    entry += f"   Snippet: {snippet}\n"
                block += entry

        if total_chars + len(block) > MAX_PROMPT_CHARS:
            break
        lines.append(block)
        total_chars += len(block)

    return "".join(lines)


def parse_gpt_response(text, article_count, sources_covered):
    """
    Parse GPT-4o Markdown response into structured JSON.
    Extracts executive summary and per-source bullet lists.
    """
    # Extract executive summary
    exec_match = re.search(
        r"##\s*Executive Summary\s*\n+(.*?)(?=##\s*Source Breakdown|$)",
        text, re.DOTALL | re.IGNORECASE
    )
    executive_summary = exec_match.group(1).strip() if exec_match else text[:500].strip()

    # Extract per-source sections
    source_sections = []
    for source_name in SOURCE_ORDER:
        # Match ### SourceName block
        pattern = re.compile(
            r"###\s*" + re.escape(source_name) + r"\s*\n(.*?)(?=###|\Z)",
            re.DOTALL | re.IGNORECASE
        )
        m = pattern.search(text)
        if not m:
            source_sections.append({"source": source_name, "bullets": []})
            continue

        block = m.group(1).strip()
        if "no articles this week" in block.lower():
            source_sections.append({"source": source_name, "bullets": ["No articles this week."]})
            continue

        bullets = []
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("- ") or line.startswith("• "):
                bullets.append(line.lstrip("-•").strip())
            elif line.startswith("* "):
                bullets.append(line[2:].strip())
        source_sections.append({"source": source_name, "bullets": bullets})

    return {
        "week_of": date.today().isoformat(),
        "article_count": article_count,
        "sources_covered": sources_covered,
        "executive_summary": executive_summary,
        "source_sections": source_sections,
        "raw_digest_markdown": text,
    }


def call_gpt4o(client, user_prompt):
    """Call GPT-4o with retry on rate limit."""
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=1500,
            )
            return response.choices[0].message.content
        except RateLimitError:
            if attempt == 0:
                print(f"    GPT-4o rate limit — waiting {RATE_LIMIT_SLEEP}s and retrying...")
                time.sleep(RATE_LIMIT_SLEEP)
            else:
                raise
        except APITimeoutError:
            if attempt == 0:
                print("    GPT-4o timeout — retrying immediately...")
                time.sleep(2)
            else:
                raise


def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run fetch_mining_news.py first.")
        return

    with open(INPUT_FILE) as f:
        articles = json.load(f)

    print("=" * 60)
    print("  Step 2: Summarize with GPT-4o")
    print(f"  Articles loaded: {len(articles)}")
    print("=" * 60)

    if not articles:
        print("  WARNING: No articles found. Writing empty summary.")
        summary = {
            "week_of": date.today().isoformat(),
            "article_count": 0,
            "sources_covered": [],
            "executive_summary": (
                "No mining news articles were retrieved this week. "
                "Please check the fetch logs and verify RSS feed availability."
            ),
            "source_sections": [{"source": s, "bullets": ["No articles this week."]} for s in SOURCE_ORDER],
            "raw_digest_markdown": "",
        }
        with open(OUTPUT_FILE, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"Output written to {OUTPUT_FILE}")
        return

    # Group articles by source
    articles_by_source = {}
    for art in articles:
        src = art["source"]
        articles_by_source.setdefault(src, []).append(art)

    sources_covered = [s for s in SOURCE_ORDER if s in articles_by_source]
    print(f"\n  Sources with articles: {', '.join(sources_covered)}")
    for src, arts in articles_by_source.items():
        print(f"    {src}: {len(arts)} articles")

    # Build prompt
    user_prompt = build_user_prompt(articles_by_source)
    print(f"\n  Prompt length: {len(user_prompt):,} chars")

    # Call GPT-4o
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in .env")
        return

    client = OpenAI(api_key=api_key)
    print("  Calling GPT-4o...")

    try:
        gpt_response = call_gpt4o(client, user_prompt)
    except Exception as e:
        print(f"  ERROR calling GPT-4o: {e}")
        print("  Writing error summary and continuing...")
        gpt_response = (
            "## Executive Summary\n\n"
            "The GPT-4o summarization step failed this week. "
            "Please run summarize_news.py manually to regenerate the digest.\n\n"
            "## Source Breakdown\n\n"
            + "\n".join(f"### {s}\n- (summarization unavailable)" for s in SOURCE_ORDER)
        )

    # Parse response
    summary = parse_gpt_response(gpt_response, len(articles), sources_covered)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n  Executive summary: {len(summary['executive_summary'])} chars")
    print(f"  Source sections: {len(summary['source_sections'])}")
    print(f"\nOutput written to {OUTPUT_FILE}")
    print("Next step: run tools/send_email_digest.py")


if __name__ == "__main__":
    main()
