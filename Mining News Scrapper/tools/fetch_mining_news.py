"""
tools/fetch_mining_news.py

Fetches mining news articles from the past 7 days across 5 top industry publications.
Primary method: RSS/Atom feed via feedparser.
Fallback: BeautifulSoup HTML scraping (if RSS unavailable or returns 0 entries).

Input:   None (fetches from internet)
Output:  .tmp/news_articles.json

Article schema:
  {source, title, url, published_date (ISO8601 or null), snippet (max 1000 chars), paywall}
"""

import json
import ssl
import time
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

PROJECT_DIR = Path(__file__).parent.parent
TMP_DIR = PROJECT_DIR / ".tmp"
OUTPUT_FILE = TMP_DIR / "news_articles.json"

REQUEST_TIMEOUT = 10
INTER_SOURCE_DELAY = 2       # seconds between sources (politeness)
MAX_SNIPPET_CHARS = 1000
LOOKBACK_DAYS = 7

# Use a realistic browser user-agent to avoid bot detection on some sites
SESSION_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

SOURCES = [
    {
        # Direct RSS — works fine
        "name": "Mining.com",
        "rss_url": "https://www.mining.com/feed/",
        "fallback_rss_url": None,
        "fallback_html_url": None,
        "has_paywall": False,
    },
    {
        # Direct RSS — works fine (paywalled: headlines + teaser only)
        "name": "The Northern Miner",
        "rss_url": "https://www.northernminer.com/feed/",
        "fallback_rss_url": None,
        "fallback_html_url": None,
        "has_paywall": True,
    },
    {
        # Direct RSS blocked by Cloudflare — use Google News site-specific query
        "name": "Mining Journal",
        "rss_url": "https://news.google.com/rss/search?q=site:mining-journal.com&hl=en-US&gl=US&ceid=US:en",
        "fallback_rss_url": None,
        "fallback_html_url": None,
        "has_paywall": False,
    },
    {
        # Direct RSS blocked by Cloudflare — use Google News site-specific query
        "name": "Mining Magazine",
        "rss_url": "https://news.google.com/rss/search?q=site:miningmagazine.com&hl=en-US&gl=US&ceid=US:en",
        "fallback_rss_url": None,
        "fallback_html_url": None,
        "has_paywall": False,
    },
    {
        # Direct RSS blocked by Cloudflare — use Google News site-specific query
        "name": "Mining Weekly",
        "rss_url": "https://news.google.com/rss/search?q=site:miningweekly.com&hl=en-US&gl=US&ceid=US:en",
        "fallback_rss_url": None,
        "fallback_html_url": None,
        "has_paywall": False,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def cutoff_date():
    return datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)


def parse_entry_date(entry):
    """Return a timezone-aware datetime from a feedparser entry, or None."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def clean_html(raw):
    """Strip HTML tags and return plain text, truncated to MAX_SNIPPET_CHARS."""
    if not raw:
        return ""
    try:
        text = BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)
    except Exception:
        text = raw
    # Collapse whitespace
    text = " ".join(text.split())
    return text[:MAX_SNIPPET_CHARS]


def is_allowed_by_robots(base_url, path):
    """Return True if path is crawlable per robots.txt (fail-open)."""
    try:
        robots_url = f"{base_url}/robots.txt"
        resp = requests.get(robots_url, headers=SESSION_HEADERS, timeout=5, allow_redirects=True)
        if resp.status_code != 200:
            return True
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.parse(resp.text.splitlines())
        return rp.can_fetch(SESSION_HEADERS["User-Agent"], f"{base_url}{path}")
    except Exception:
        return True


def fetch_html(url, verify_ssl=True):
    """Fetch a URL, return BeautifulSoup or None. Retries once on failure."""
    for attempt in range(2):
        try:
            resp = requests.get(
                url,
                headers=SESSION_HEADERS,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
                verify=verify_ssl,
                stream=True,
            )
            if resp.status_code != 200:
                return None
            raw = resp.raw.read(1 * 1024 * 1024, decode_content=True)
            return BeautifulSoup(raw, "lxml")
        except ssl.SSLError:
            if verify_ssl:
                print(f"    SSL error on {url} — retrying without verification")
                return fetch_html(url, verify_ssl=False)
            return None
        except (requests.ConnectionError, requests.Timeout, requests.TooManyRedirects):
            if attempt == 0:
                time.sleep(3)
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# RSS fetch
# ---------------------------------------------------------------------------

def fetch_rss(rss_url):
    """
    Parse an RSS/Atom feed. Returns list of feedparser entries (may be empty).
    Checks bozo flag (malformed XML) and HTTP status.
    """
    try:
        result = feedparser.parse(
            rss_url,
            request_headers={"User-Agent": SESSION_HEADERS["User-Agent"]},
        )
    except Exception as e:
        print(f"    feedparser exception: {e}")
        return []

    status = result.get("status", 0)
    bozo = result.get("bozo", False)
    entries = result.get("entries", [])

    if status and status not in (200, 301, 302):
        print(f"    RSS HTTP {status} — skipping")
        return []
    if bozo and not entries:
        print(f"    RSS malformed XML and 0 entries — skipping")
        return []

    return entries


def entries_to_articles(entries, source_name, has_paywall):
    """Convert feedparser entries to our article dicts, filtering by date."""
    cutoff = cutoff_date()
    articles = []

    for entry in entries:
        pub_dt = parse_entry_date(entry)

        # Skip articles older than LOOKBACK_DAYS (if we know the date)
        if pub_dt and pub_dt < cutoff:
            continue

        # Extract snippet: prefer full content, fall back to summary, then title
        raw_snippet = ""
        if hasattr(entry, "content") and entry.content:
            raw_snippet = entry.content[0].get("value", "")
        if not raw_snippet:
            raw_snippet = getattr(entry, "summary", "") or ""

        snippet = clean_html(raw_snippet)

        articles.append({
            "source": source_name,
            "title": getattr(entry, "title", "").strip(),
            "url": getattr(entry, "link", "").strip(),
            "published_date": pub_dt.isoformat() if pub_dt else None,
            "snippet": snippet,
            "paywall": has_paywall,
        })

    return articles


# ---------------------------------------------------------------------------
# HTML fallback scrape
# ---------------------------------------------------------------------------

def fetch_html_articles(source):
    """
    Fallback: scrape the publication's news listing page for headlines + URLs.
    Returns minimal article dicts (snippet will be empty).
    Only used when RSS completely fails.
    """
    base_html = source.get("fallback_html_url")
    if not base_html:
        return []

    parsed = urlparse(base_html)
    base_domain = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path or "/"

    if not is_allowed_by_robots(base_domain, path):
        print(f"    robots.txt disallows {path} — skipping HTML fallback")
        return []

    soup = fetch_html(base_html)
    if not soup:
        print(f"    HTML fallback fetch failed for {base_html}")
        return []

    articles = []
    # Look for article links — try common patterns
    candidates = (
        soup.find_all("article")
        or soup.find_all(class_=lambda c: c and "article" in c.lower())
        or soup.find_all("h2")
    )

    for el in candidates[:20]:  # cap at 20 per source
        link = el.find("a", href=True) if el.name != "a" else el
        if not link:
            continue
        href = link.get("href", "")
        if not href.startswith("http"):
            href = urljoin(base_domain, href)
        title = link.get_text(strip=True) or el.get_text(strip=True)
        title = title[:200]
        if title and href:
            articles.append({
                "source": source["name"],
                "title": title,
                "url": href,
                "published_date": None,
                "snippet": "",
                "paywall": source["has_paywall"],
            })

    return articles


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fetch_source(source):
    """Fetch one source. Returns list of article dicts."""
    name = source["name"]
    print(f"\n  [{name}]")

    # Try primary RSS
    entries = fetch_rss(source["rss_url"])
    if entries:
        articles = entries_to_articles(entries, name, source["has_paywall"])
        print(f"    RSS OK — {len(entries)} entries, {len(articles)} within {LOOKBACK_DAYS} days")
        return articles

    print(f"    Primary RSS returned 0 entries")

    # Try fallback RSS
    if source.get("fallback_rss_url"):
        print(f"    Trying fallback RSS: {source['fallback_rss_url']}")
        entries = fetch_rss(source["fallback_rss_url"])
        if entries:
            articles = entries_to_articles(entries, name, source["has_paywall"])
            print(f"    Fallback RSS OK — {len(entries)} entries, {len(articles)} within {LOOKBACK_DAYS} days")
            return articles
        print(f"    Fallback RSS also returned 0 entries")

    # Try HTML fallback
    if source.get("fallback_html_url"):
        print(f"    Trying HTML fallback: {source['fallback_html_url']}")
        articles = fetch_html_articles(source)
        if articles:
            print(f"    HTML fallback OK — {len(articles)} headlines")
            return articles
        print(f"    HTML fallback returned 0 articles")

    print(f"    WARNING: All fetch methods failed for {name} — skipping")
    return []


def main():
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Step 1: Fetch Mining News")
    print(f"  Window: past {LOOKBACK_DAYS} days")
    print("=" * 60)

    all_articles = []

    for i, source in enumerate(SOURCES):
        articles = fetch_source(source)
        all_articles.extend(articles)

        if i < len(SOURCES) - 1:
            time.sleep(INTER_SOURCE_DELAY)

    # Summary
    print(f"\n--- Fetch complete ---")
    print(f"  Total articles: {len(all_articles)}")
    by_source = {}
    for a in all_articles:
        by_source[a["source"]] = by_source.get(a["source"], 0) + 1
    for src, count in by_source.items():
        print(f"    {src}: {count}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_articles, f, indent=2)

    print(f"\nOutput written to {OUTPUT_FILE}")
    print("Next step: run tools/summarize_news.py")


if __name__ == "__main__":
    main()
