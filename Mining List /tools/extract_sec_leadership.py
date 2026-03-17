"""
tools/extract_sec_leadership.py

For each EDGAR-listed mining company (has a CIK), downloads the most recent
10-K annual report and parses it to extract:
  - CEO name and title
  - General Counsel / Chief Legal Officer name and title
  - Major projects and countries of operation
  - Tons of ore processed
  - Jurisdictions of operation

Required .env keys:
    EDGAR_USER_AGENT   (format: "Your Name your@email.com")

Input:   .tmp/companies_yfinance.json
Output:  .tmp/companies_leadership.json
"""

import json
import os
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

EDGAR_USER_AGENT = os.getenv("EDGAR_USER_AGENT", "Mining Research bot@example.com")
INPUT_FILE = Path(".tmp/companies_yfinance.json")
OUTPUT_FILE = Path(".tmp/companies_leadership.json")
EDGAR_DELAY = 0.15
MAX_10K_BYTES = 150_000  # only download first 150KB of 10-K

HEADERS = {
    "User-Agent": EDGAR_USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
}

# Titles that indicate CEO
CEO_TITLE_PATTERNS = [
    r"chief\s+executive\s+officer",
    r"\bC\.?E\.?O\.?\b",
    r"president\s+and\s+chief\s+executive",
    r"president\s*[,/&]\s*chief\s+executive",
]

# Titles that indicate General Counsel / CLO
GC_TITLE_PATTERNS = [
    r"general\s+counsel",
    r"chief\s+legal\s+officer",
    r"\bC\.?L\.?O\.?\b",
    r"executive\s+vice\s+president.*?legal",
    r"senior\s+vice\s+president.*?legal",
    r"vice\s+president.*?general\s+counsel",
]

# Countries reference list (subset of commonly-operating mining jurisdictions)
MINING_COUNTRIES = [
    "United States", "Canada", "Australia", "Mexico", "Chile", "Peru",
    "Brazil", "Argentina", "Colombia", "Bolivia", "Ecuador",
    "South Africa", "Ghana", "Tanzania", "Democratic Republic of Congo",
    "Zambia", "Zimbabwe", "Botswana", "Mali", "Burkina Faso", "Guinea",
    "Indonesia", "Philippines", "Papua New Guinea", "Mongolia",
    "Kazakhstan", "Kyrgyzstan", "Uzbekistan",
    "Russia", "Finland", "Sweden", "Norway",
    "Nevada", "Alaska", "Arizona", "Colorado",  # US states common in mining
    "Ontario", "British Columbia", "Quebec", "Saskatchewan",  # Canadian provinces
    "Western Australia", "Queensland", "New South Wales",  # Australian states
]


def padded_cik(cik):
    return str(cik).zfill(10)


def get_latest_10k_accession(cik):
    """
    Query EDGAR submissions API to find the most recent annual report filing.
    Returns (accession_number, filing_date, primary_document_filename) or (None, None, None).
    The primary_document_filename comes directly from the submissions JSON, so we can
    construct the document URL without fetching the filing index page (which often returns 503).
    """
    url = f"https://data.sec.gov/submissions/CIK{padded_cik(cik)}.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    WARNING: Could not fetch submissions for CIK {cik}: {e}")
        return None, None, None

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    accessions = filings.get("accessionNumber", [])
    dates = filings.get("filingDate", [])
    primary_docs = filings.get("primaryDocument", [])

    # Accept 10-K (US domestic), 20-F (foreign private issuers — Canada, Australia, etc.),
    # 10-KSB (smaller reporting companies, older filings), and their amendments
    ANNUAL_REPORT_FORMS = {"10-K", "10-K/A", "10-KSB", "10-KSB/A", "20-F", "20-F/A"}
    for i, (form, accession, date) in enumerate(zip(forms, accessions, dates)):
        if form in ANNUAL_REPORT_FORMS:
            primary_doc = primary_docs[i] if i < len(primary_docs) else None
            return accession, date, primary_doc

    return None, None, None


def get_10k_primary_document_url(cik, accession):
    """
    Fetch the filing index page and find the primary 10-K document URL.
    Returns the full URL string or None.
    """
    accession_nodash = accession.replace("-", "")
    index_url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/"
        f"{accession_nodash}/{accession_nodash}-index.htm"
    )
    try:
        resp = requests.get(index_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        print(f"    WARNING: Could not fetch filing index: {e}")
        return None

    # Look for the table row with type "10-K" and get the document link
    ANNUAL_REPORT_FORMS = {"10-K", "10-K/A", "10-KSB", "10-KSB/A", "20-F", "20-F/A"}
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) >= 4:
            doc_type = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            if doc_type in ANNUAL_REPORT_FORMS:
                link = cells[2].find("a") if len(cells) > 2 else None
                if link and link.get("href"):
                    href = link["href"]
                    if href.startswith("/"):
                        return f"https://www.sec.gov{href}"
                    return href

    # Fallback: find first .htm link that looks like a primary document
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.endswith(".htm") and accession_nodash[:10] in href:
            if href.startswith("/"):
                return f"https://www.sec.gov{href}"
            return href

    return None


def download_10k_text(url):
    """Download the 10-K and return plain text (first MAX_10K_BYTES only)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, stream=True)
        resp.raise_for_status()
        raw = b""
        for chunk in resp.iter_content(chunk_size=8192):
            raw += chunk
            if len(raw) >= MAX_10K_BYTES:
                break
        soup = BeautifulSoup(raw[:MAX_10K_BYTES], "lxml")
        return soup.get_text(separator=" ", strip=True)
    except Exception as e:
        print(f"    WARNING: Could not download 10-K: {e}")
        return ""


def find_section(text, start_marker_pattern, end_marker_pattern):
    """Extract a section of the 10-K between two regex markers."""
    match = re.search(
        start_marker_pattern + r"(.*?)" + end_marker_pattern,
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return match.group(1)
    # Try without end marker — just take next 5000 chars after start
    start_match = re.search(start_marker_pattern, text, re.IGNORECASE)
    if start_match:
        return text[start_match.end():start_match.end() + 5000]
    return ""


def extract_name_for_title(section_text, title_patterns):
    """
    Given a block of 10-K text and a list of title regex patterns,
    find the person's name associated with that title.

    Strategy: look for "Name ... Title" or "Title ... Name" patterns.
    Common 10-K formats:
      John Smith   Chief Executive Officer   Age 55
      Chief Executive Officer — John Smith
    Returns (name, matched_title) or (None, None).
    """
    combined = "|".join(f"(?:{p})" for p in title_patterns)
    # Pattern 1: NAME (all-caps or Title Case) followed by title within 200 chars
    # e.g. "JOHN SMITH\n\nChief Executive Officer"
    pattern1 = re.compile(
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})\s{0,50}(?:[A-Za-z,\.]*\s{0,20})?(" + combined + r")",
        re.IGNORECASE,
    )
    # Pattern 2: title followed by name within 200 chars
    pattern2 = re.compile(
        r"(" + combined + r")\s{0,50}(?:[,\-–]?\s{0,20})?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})",
        re.IGNORECASE,
    )

    for pattern in [pattern1, pattern2]:
        for m in pattern.finditer(section_text):
            groups = m.groups()
            # Determine which group is the name and which is the title
            if pattern is pattern1:
                name_candidate, title_candidate = groups[0], groups[1]
            else:
                title_candidate, name_candidate = groups[0], groups[1]

            # Validate name (not a known false positive)
            name = name_candidate.strip()
            title = title_candidate.strip()
            bad_words = {
                "the", "our", "its", "this", "that", "with", "and", "for",
                "has", "are", "was", "not", "all", "any", "may", "such",
                "item", "part", "section", "annual", "report", "form",
            }
            if name.lower().split()[0] in bad_words:
                continue
            if len(name.split()) < 2 or len(name.split()) > 5:
                continue
            return name, title

    return None, None


def extract_projects_and_jurisdictions(text):
    """
    Parse the ITEM 2 PROPERTIES section for project names and countries.
    Returns (projects_list, countries_list, jurisdictions_string).
    """
    section = find_section(
        text,
        r"ITEM\s+2[\.\s]+PROPERTIES",
        r"ITEM\s+3[\.\s]",
    )
    if not section:
        section = text  # fall back to full text

    projects = []
    countries = []

    # Mine/project name patterns
    mine_pattern = re.compile(
        r"([A-Z][A-Za-z\s]{2,30})\s+(?:mine|project|deposit|property|operation|complex)\b",
        re.IGNORECASE,
    )
    for m in mine_pattern.finditer(section):
        name = m.group(1).strip()
        # Filter out sentence starters / generic words
        if len(name.split()) <= 5 and name.lower() not in {
            "the", "our", "its", "this", "a", "an"
        }:
            if name not in projects:
                projects.append(name)
        if len(projects) >= 10:
            break

    # Country mentions
    for country in MINING_COUNTRIES:
        if re.search(r'\b' + re.escape(country) + r'\b', section, re.IGNORECASE):
            if country not in countries:
                countries.append(country)

    jurisdictions = "; ".join(countries) if countries else ""
    return projects[:10], countries, jurisdictions


def extract_tons_ore(text):
    """
    Search for throughput / ore processed figures.
    Returns a string like "12.5 million tons" or None.
    """
    patterns = [
        r'(\d[\d,\.]+)\s*(?:million)?\s*(?:short\s+)?tons?\s+(?:of\s+)?(?:ore|material|rock|throughput)',
        r'(?:ore\s+)?(?:throughput|processed|milled)\s+(?:of\s+)?(\d[\d,\.]+)\s*(?:million)?\s*(?:short\s+)?tons?',
        r'(\d[\d,\.]+)\s*(?:million)?\s*(?:metric\s+)?tonnes?\s+(?:of\s+)?(?:ore|material)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            # Return the full match for context
            start = max(0, m.start() - 10)
            end = min(len(text), m.end() + 20)
            return text[start:end].strip()
    return None


def process_company(company):
    """Run full EDGAR extraction for one company. Returns updated company dict."""
    cik = company.get("cik")
    if not cik:
        return company  # No CIK — skip EDGAR enrichment

    print(f"  CIK {cik}: {company.get('name', '')[:50]}")

    # Step 1: Find latest annual report — submissions JSON includes primaryDocument
    # filename so we can skip the filing index page fetch entirely (index.htm often 503s)
    accession, filing_date, primary_doc = get_latest_10k_accession(cik)
    time.sleep(EDGAR_DELAY)

    if not accession:
        print(f"    No annual report found for CIK {cik}")
        company["sec_source_url"] = None
        return company

    # Step 2: Build document URL from primaryDocument field (no index page needed)
    if primary_doc:
        accession_nodash = accession.replace("-", "")
        doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/"
            f"{accession_nodash}/{primary_doc}"
        )
    else:
        # Fallback: fetch the filing index page if primaryDocument wasn't in submissions JSON
        doc_url = get_10k_primary_document_url(cik, accession)
        time.sleep(EDGAR_DELAY)

    if not doc_url:
        print(f"    Could not locate primary document for CIK {cik}")
        return company

    company["sec_source_url"] = doc_url

    # Step 3: Download 10-K text
    text = download_10k_text(doc_url)
    time.sleep(EDGAR_DELAY)

    if not text:
        return company

    # Step 4: Find executive officers section
    exec_section = find_section(
        text,
        r"EXECUTIVE\s+OFFICERS",
        r"(?:ITEM\s+\d|PART\s+II|SECURITY\s+OWNERSHIP)",
    )

    # Step 5: Extract CEO
    if not company.get("ceo_name"):
        ceo_name, ceo_title = extract_name_for_title(exec_section or text, CEO_TITLE_PATTERNS)
        if ceo_name:
            company["ceo_name"] = ceo_name
            company["ceo_title"] = ceo_title
            print(f"    CEO: {ceo_name}")

    # Step 6: Extract General Counsel
    if not company.get("gc_name"):
        gc_name, gc_title = extract_name_for_title(exec_section or text, GC_TITLE_PATTERNS)
        if gc_name:
            company["gc_name"] = gc_name
            company["gc_title"] = gc_title
            print(f"    GC: {gc_name} ({gc_title})")
        else:
            print(f"    GC: not found in executive section")

    # Step 7: Extract projects and jurisdictions
    if not company.get("projects"):
        projects, countries, jurisdictions = extract_projects_and_jurisdictions(text)
        if projects:
            company["projects"] = projects
            print(f"    Projects: {', '.join(projects[:3])}{'...' if len(projects) > 3 else ''}")
        if countries:
            company["project_countries"] = countries
        if jurisdictions and not company.get("jurisdictions"):
            company["jurisdictions"] = jurisdictions

    # Step 8: Extract tons ore processed
    if not company.get("tons_ore_processed"):
        tons = extract_tons_ore(text)
        if tons:
            company["tons_ore_processed"] = tons

    # Track data source
    sources = company.get("data_sources") or []
    if "EDGAR_10K" not in sources:
        sources.append("EDGAR_10K")
    company["data_sources"] = sources

    return company


def main():
    if not EDGAR_USER_AGENT or EDGAR_USER_AGENT == "Mining Research bot@example.com":
        print("WARNING: EDGAR_USER_AGENT is not set in .env. SEC may block requests.")
        print("Set it to: EDGAR_USER_AGENT=Your Name your@email.com\n")

    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run enrich_yfinance.py first.")
        return

    with open(INPUT_FILE) as f:
        companies = json.load(f)

    print(f"=== Phase 3: Extract SEC Leadership from 10-K Filings ===\n")
    print(f"Loaded {len(companies)} companies from {INPUT_FILE}")

    # Checkpoint/resume: load existing output
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)
        done_ciks = {
            c.get("cik")
            for c in existing
            if c.get("cik") and c.get("sec_source_url") is not None
        }
        print(f"Resuming: {len(done_ciks)} already processed.")
    else:
        existing = []
        done_ciks = set()

    results = list(existing)
    existing_by_cik = {c.get("cik"): i for i, c in enumerate(results) if c.get("cik")}
    existing_by_ticker = {
        (c.get("ticker") or "").upper(): i
        for i, c in enumerate(results)
        if c.get("ticker")
    }

    to_process = [
        c for c in companies
        if c.get("cik") not in done_ciks
    ]
    # Also pass through non-EDGAR companies unchanged
    non_edgar = [c for c in companies if not c.get("cik")]
    print(f"EDGAR companies to process: {len(to_process)}")
    print(f"Non-EDGAR companies (pass-through): {len(non_edgar)}\n")

    for i, company in enumerate(to_process):
        print(f"[{i+1}/{len(to_process)}]", end=" ")
        enriched = process_company(company)

        # Update or append
        cik = enriched.get("cik")
        ticker = (enriched.get("ticker") or "").upper()
        if cik and cik in existing_by_cik:
            results[existing_by_cik[cik]] = enriched
        elif ticker and ticker in existing_by_ticker:
            results[existing_by_ticker[ticker]] = enriched
        else:
            results.append(enriched)

        # Write checkpoint
        with open(OUTPUT_FILE, "w") as f:
            json.dump(results, f, indent=2)

    # Append non-EDGAR companies that aren't already in results
    result_tickers = {(r.get("ticker") or "").upper() for r in results}
    for c in non_edgar:
        t = (c.get("ticker") or "").upper()
        if t not in result_tickers:
            results.append(c)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    ceos = sum(1 for c in results if c.get("ceo_name"))
    gcs = sum(1 for c in results if c.get("gc_name"))
    print(f"\nDone. {len(results)} total records.")
    print(f"  CEO found: {ceos}")
    print(f"  GC found: {gcs}")
    print(f"\nOutput written to {OUTPUT_FILE}")
    print("Next step: run tools/scrape_company_website.py")


if __name__ == "__main__":
    main()
