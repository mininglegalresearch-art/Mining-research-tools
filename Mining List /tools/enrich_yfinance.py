"""
tools/enrich_yfinance.py

Enriches each mining company record with financial and metadata from Yahoo Finance.
For each company with a ticker, fetches: exchange, revenue, market cap, website,
country, sector, and fiscal year data.

Input:   .tmp/companies_raw.json
Output:  .tmp/companies_yfinance.json  (same records + new fields)

New fields added:
    long_name, exchange_yf, sector, industry, country, website,
    market_cap, total_revenue, revenue_currency, revenue_year,
    fiscal_year_end, yfinance_error (bool)
"""

import json
import time
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

INPUT_FILE = Path(".tmp/companies_raw.json")
OUTPUT_FILE = Path(".tmp/companies_yfinance.json")
CIK_TICKER_CACHE = Path(".tmp/cik_ticker_map.json")
DELAY_SECONDS = 2  # between yfinance calls to avoid rate limits

EDGAR_HEADERS = {
    "User-Agent": "Mining Legal Research mininglegalresearch@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}


def load_cik_ticker_map():
    """
    Fetch SEC's company_tickers.json which maps CIK -> ticker for all
    SEC-registered companies. Cached locally to avoid re-fetching.
    Returns dict: {cik_string: ticker}
    """
    if CIK_TICKER_CACHE.exists():
        print("Loading CIK→ticker map from cache...")
        with open(CIK_TICKER_CACHE) as f:
            return json.load(f)

    print("Fetching CIK→ticker map from SEC (one-time download)...")
    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=EDGAR_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        # data format: {"0": {"cik_str": 1234, "ticker": "GOLD", "title": "..."}, ...}
        cik_map = {
            str(v["cik_str"]): v["ticker"].upper()
            for v in data.values()
            if v.get("ticker")
        }
        with open(CIK_TICKER_CACHE, "w") as f:
            json.dump(cik_map, f)
        print(f"  Loaded {len(cik_map)} CIK→ticker mappings.")
        return cik_map
    except Exception as e:
        print(f"  WARNING: Could not fetch CIK→ticker map: {e}")
        return {}


def get_revenue_from_financials(ticker_obj):
    """
    Fallback: pull total revenue from the income statement DataFrame
    when .info['totalRevenue'] is None.
    Returns (revenue_value, year_string) or (None, None).
    """
    try:
        financials = ticker_obj.financials
        if financials is None or financials.empty:
            return None, None
        # Row label varies: 'Total Revenue', 'Total Revenues'
        for label in ["Total Revenue", "Total Revenues", "Revenue"]:
            if label in financials.index:
                row = financials.loc[label]
                # Columns are datetime objects — take the most recent
                most_recent_col = row.index[0]
                value = row.iloc[0]
                if pd.notna(value):
                    year = most_recent_col.year if hasattr(most_recent_col, "year") else None
                    return int(value), str(year) if year else None
    except Exception:
        pass
    return None, None


def enrich_ticker(company):
    """
    Fetch yfinance data for a single company. Returns the company dict
    with new fields merged in.
    """
    ticker_sym = (company.get("ticker") or "").strip().upper()
    if not ticker_sym:
        company["yfinance_error"] = False
        company["no_active_ticker"] = True
        return company

    try:
        t = yf.Ticker(ticker_sym)
        info = t.info or {}

        # Core metadata
        company["long_name"] = info.get("longName") or company.get("name")
        company["exchange_yf"] = info.get("exchange")
        company["sector"] = info.get("sector")
        company["industry"] = info.get("industry")
        company["country"] = info.get("country")
        company["website"] = info.get("website")
        company["market_cap"] = info.get("marketCap")
        company["revenue_currency"] = info.get("financialCurrency", "USD")
        company["fiscal_year_end"] = info.get("fiscalYearEnd")

        # Revenue — try .info first, fall back to .financials
        total_revenue = info.get("totalRevenue")
        revenue_year = None

        if not total_revenue:
            total_revenue, revenue_year = get_revenue_from_financials(t)
        else:
            # Estimate the year from fiscalYearEnd if available
            fy = info.get("fiscalYearEnd")
            if fy:
                revenue_year = str(fy)[:4]  # "2023-12-31" -> "2023"

        company["total_revenue"] = total_revenue
        company["revenue_year"] = revenue_year
        company["yfinance_error"] = False

        # If exchange still unknown, use yfinance exchange
        if not company.get("exchange") and company.get("exchange_yf"):
            company["exchange"] = company["exchange_yf"]

        # Populate name from longName if missing
        if not company.get("name") and company.get("long_name"):
            company["name"] = company["long_name"]

        # Track data sources
        sources = company.get("data_sources") or []
        if "yfinance" not in sources:
            sources.append("yfinance")
        company["data_sources"] = sources

    except Exception as e:
        print(f"    WARNING: yfinance error for {ticker_sym}: {e}")
        company["yfinance_error"] = True

    return company


def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run discover_mining_companies.py first.")
        return

    with open(INPUT_FILE) as f:
        companies = json.load(f)

    print(f"=== Phase 2: Enrich with yfinance ===\n")
    print(f"Loaded {len(companies)} companies from {INPUT_FILE}")

    # Step 0: Fill in missing tickers using SEC CIK→ticker map
    cik_map = load_cik_ticker_map()
    filled = 0
    for c in companies:
        if not c.get("ticker") and c.get("cik"):
            cik_key = str(c["cik"]).lstrip("0")
            ticker = cik_map.get(cik_key)
            if ticker:
                c["ticker"] = ticker
                filled += 1
    print(f"Filled in {filled} missing tickers from SEC CIK map.\n")

    # Load existing output to support checkpoint/resume
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)
        done_tickers = {
            (c.get("ticker") or "").upper()
            for c in existing
            if not c.get("yfinance_error")
        }
        print(f"Resuming: {len(done_tickers)} already processed, skipping.")
    else:
        existing = []
        done_tickers = set()

    results = list(existing)
    # Index existing by ticker for fast lookup
    existing_by_ticker = {
        (c.get("ticker") or "").upper(): i
        for i, c in enumerate(results)
    }

    to_process = [
        c for c in companies
        if (c.get("ticker") or "").upper() not in done_tickers
    ]
    print(f"Processing {len(to_process)} remaining companies...\n")

    for i, company in enumerate(to_process):
        ticker = (company.get("ticker") or "NO_TICKER").upper()
        print(f"  [{i+1}/{len(to_process)}] {ticker} — {company.get('name', '')[:50]}")

        enriched = enrich_ticker(company)

        # Update existing record or append new
        key = (enriched.get("ticker") or "").upper()
        if key in existing_by_ticker:
            results[existing_by_ticker[key]] = enriched
        else:
            results.append(enriched)

        # Write checkpoint after each company
        with open(OUTPUT_FILE, "w") as f:
            json.dump(results, f, indent=2)

        if ticker != "NO_TICKER":
            time.sleep(DELAY_SECONDS)

    # Summary
    with_revenue = sum(1 for c in results if c.get("total_revenue"))
    with_website = sum(1 for c in results if c.get("website"))
    errors = sum(1 for c in results if c.get("yfinance_error"))

    print(f"\nDone. {len(results)} total records.")
    print(f"  Revenue found: {with_revenue}")
    print(f"  Website found: {with_website}")
    print(f"  yfinance errors: {errors}")
    print(f"\nOutput written to {OUTPUT_FILE}")
    print("Next step: run tools/extract_sec_leadership.py")


if __name__ == "__main__":
    main()
