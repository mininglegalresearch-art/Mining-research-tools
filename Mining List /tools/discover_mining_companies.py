"""
tools/discover_mining_companies.py

Discovers publicly traded mining companies from two sources:
  1. SEC EDGAR company search using mining SIC codes
  2. Google Custom Search for mining companies on other exchanges (TSX, ASX, LSE)

Required .env keys:
    EDGAR_USER_AGENT         (format: "Your Name your@email.com")
    GOOGLE_CUSTOM_SEARCH_API_KEY
    GOOGLE_CUSTOM_SEARCH_CX

Output:
    .tmp/companies_raw.json  — list of company dicts with keys:
        name, ticker, exchange, cik, source, country_of_incorporation
"""

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

EDGAR_USER_AGENT = os.getenv("EDGAR_USER_AGENT", "Mining Research bot@example.com")
GOOGLE_API_KEY = os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
GOOGLE_CX = os.getenv("GOOGLE_CUSTOM_SEARCH_CX")

OUTPUT_FILE = Path(".tmp/companies_raw.json")
EDGAR_BASE = "https://www.sec.gov/cgi-bin/browse-edgar"
EDGAR_DELAY = 0.12  # seconds between EDGAR requests (SEC rate limit: 10 req/s)

# Mining SIC codes
MINING_SIC_CODES = {
    "1000": "Metal Mining",
    "1040": "Gold and Silver Ores Mining",
    "1090": "Metal Mining Services",
    "1094": "Uranium-Radium-Vanadium Ores Mining",
    "1400": "Mining & Quarrying of Nonmetallic Minerals",
}

# Google Custom Search queries for non-EDGAR companies
SEARCH_QUERIES = [
    "publicly traded gold mining companies TSX NYSE ticker symbol list",
    "silver mining company stock ticker ASX LSE listed 2024",
    "copper mining company publicly traded NYSE TSX ASX ticker",
    "publicly traded mining companies Canada Australia exchange listed",
    "lithium cobalt mining company stock exchange ticker listed",
]

# Regex patterns to extract tickers from search snippets
TICKER_PATTERNS = [
    r'\b([A-Z]{1,5})\s*:\s*([A-Z]{1,5})\b',    # EXCHANGE:TICKER (e.g. NYSE:NEM)
    r'\(([A-Z]{1,5})\)',                           # (TICKER) in parentheses
    r'\bTicker[:\s]+([A-Z]{1,5})\b',              # Ticker: GOLD
    r'\bSymbol[:\s]+([A-Z]{1,5})\b',              # Symbol: ABX
]


def edgar_headers():
    return {
        "User-Agent": EDGAR_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    }


def fetch_edgar_sic(sic_code, start=0):
    """Fetch one page of EDGAR company results for a given SIC code."""
    params = {
        "action": "getcompany",
        "SIC": sic_code,
        "type": "10-K",
        "dateb": "",
        "owner": "include",
        "count": "100",
        "start": str(start),
        "output": "atom",
    }
    resp = requests.get(EDGAR_BASE, params=params, headers=edgar_headers(), timeout=15)
    resp.raise_for_status()
    return resp.text


def parse_edgar_atom(xml_text):
    """
    Parse EDGAR Atom feed and return list of company dicts.

    Actual EDGAR XML structure:
      <feed xmlns="http://www.w3.org/2005/Atom">
        <entry>
          <title>COMPANY NAME</title>
          <content type="text/xml">
            <company-info>
              <cik>0001234567</cik>
              <state>...</state>
            </company-info>
          </content>
        </entry>
      </feed>
    Note: tickers are NOT included in this feed — they come from company_tickers.json.
    """
    companies = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return companies

    atom_ns = "http://www.w3.org/2005/Atom"
    ns = {"atom": atom_ns}

    entries = root.findall("atom:entry", ns)

    for entry in entries:
        # Company name is in <title>
        title_el = entry.find("atom:title", ns)
        name = title_el.text.strip() if title_el is not None and title_el.text else ""

        # All nested elements are also in the Atom namespace
        cik = ""
        state = ""
        cik_el = entry.find("atom:content/atom:company-info/atom:cik", ns)
        state_el = entry.find("atom:content/atom:company-info/atom:state", ns)
        if cik_el is not None and cik_el.text:
            cik = cik_el.text.strip().lstrip("0")
        if state_el is not None and state_el.text:
            state = state_el.text.strip()

        if not name:
            continue

        companies.append({
            "name": name,
            "ticker": None,   # Not in EDGAR Atom; resolved from company_tickers.json in Phase 2
            "exchange": None,
            "cik": cik or None,
            "source": "EDGAR",
            "country_of_incorporation": state or None,
        })

    return companies


def discover_from_edgar():
    """Sweep all mining SIC codes on EDGAR and return company list."""
    all_companies = []
    for sic, sic_name in MINING_SIC_CODES.items():
        print(f"  EDGAR SIC {sic} ({sic_name})...")
        start = 0
        while True:
            try:
                xml_text = fetch_edgar_sic(sic, start=start)
                batch = parse_edgar_atom(xml_text)
                if not batch:
                    break
                all_companies.extend(batch)
                print(f"    Page start={start}: {len(batch)} companies")
                start += 100
                time.sleep(EDGAR_DELAY)
                if len(batch) < 100:
                    break
            except requests.RequestException as e:
                print(f"    WARNING: EDGAR request failed (SIC {sic}, start={start}): {e}")
                break
    return all_companies


def google_search(query):
    """Run one Google Custom Search query and return list of results."""
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        return []
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CX,
        "q": query,
        "num": 10,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except requests.RequestException as e:
        print(f"    WARNING: Google Search failed for query '{query}': {e}")
        return []


def extract_companies_from_search_results(results):
    """
    Parse Google search result snippets for company names and ticker symbols.
    Returns a list of partial company dicts (name + ticker when detectable).
    """
    companies = []
    for item in results:
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        text = f"{title} {snippet}"

        # Try to find exchange:ticker patterns (most reliable)
        for pattern in TICKER_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    exchange, ticker = match[0], match[1]
                else:
                    exchange, ticker = None, match
                # Filter out noise — real tickers are 1-5 uppercase letters
                if ticker and 1 <= len(ticker) <= 5 and ticker.isalpha():
                    companies.append({
                        "name": title.split("|")[0].split("-")[0].strip(),
                        "ticker": ticker.upper(),
                        "exchange": exchange or None,
                        "cik": None,
                        "source": "google_search",
                        "country_of_incorporation": None,
                    })
    return companies


def discover_from_google():
    """Search Google for mining companies and extract company/ticker data."""
    all_companies = []
    if not GOOGLE_API_KEY:
        print("  GOOGLE_CUSTOM_SEARCH_API_KEY not set — skipping Google Search discovery.")
        return all_companies

    for query in SEARCH_QUERIES:
        print(f"  Google Search: {query[:60]}...")
        results = google_search(query)
        batch = extract_companies_from_search_results(results)
        print(f"    Found {len(batch)} ticker mentions")
        all_companies.extend(batch)
        time.sleep(0.5)  # avoid hammering Google API

    return all_companies


def deduplicate(companies):
    """
    Deduplicate by ticker symbol.
    Prefer EDGAR records (have CIK) over Google Search records.
    Companies with no ticker are kept but not deduped against each other.
    """
    by_ticker = {}
    no_ticker = []

    for c in companies:
        ticker = (c.get("ticker") or "").upper().strip()
        if not ticker:
            no_ticker.append(c)
            continue
        if ticker not in by_ticker:
            by_ticker[ticker] = c
        else:
            existing = by_ticker[ticker]
            # Prefer EDGAR source
            if c.get("source") == "EDGAR" and existing.get("source") != "EDGAR":
                # Merge: keep EDGAR record but add any fields the Google record had
                c["source"] = "EDGAR+google_search"
                by_ticker[ticker] = c
            elif c.get("source") != "EDGAR" and existing.get("source") == "EDGAR":
                pass  # keep existing EDGAR record
            else:
                # Both same source — keep first, merge exchange if missing
                if not existing.get("exchange") and c.get("exchange"):
                    existing["exchange"] = c["exchange"]

    result = list(by_ticker.values()) + no_ticker
    return result


def main():
    OUTPUT_FILE.parent.mkdir(exist_ok=True)

    print("=== Phase 1: Discover Mining Companies ===\n")

    print("Querying SEC EDGAR for mining SIC codes...")
    edgar_companies = discover_from_edgar()
    print(f"EDGAR total: {len(edgar_companies)} records\n")

    print("Querying Google Custom Search for mining companies...")
    google_companies = discover_from_google()
    print(f"Google Search total: {len(google_companies)} records\n")

    all_companies = edgar_companies + google_companies
    print(f"Combined before dedup: {len(all_companies)}")

    deduped = deduplicate(all_companies)
    print(f"After deduplication: {len(deduped)} unique companies")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(deduped, f, indent=2)

    print(f"\nOutput written to {OUTPUT_FILE}")
    print("Next step: run tools/enrich_yfinance.py")


if __name__ == "__main__":
    main()
