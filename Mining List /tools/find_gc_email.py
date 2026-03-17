"""
tools/find_gc_email.py

Attempts to find the email address for the General Counsel / CLO (or most senior
lawyer) at each mining company using a cascade of free strategies:

  Strategy 1 — Domain pattern generation + SMTP VRFY validation
  Strategy 2 — Google Custom Search for visible email in press releases / bios
  Strategy 3 — SEC 10-K cover page email extraction
  Strategy 4 — LinkedIn search URL construction (always populated, manual fallback)

Required .env keys:
    GOOGLE_CUSTOM_SEARCH_API_KEY
    GOOGLE_CUSTOM_SEARCH_CX

Input:   .tmp/companies_enriched.json
Output:  .tmp/companies_with_email.json

Also writes:
    .tmp/domain_cache.json  — caches verified email patterns per domain
"""

import json
import os
import re
import smtplib
import socket
import time
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
GOOGLE_CX = os.getenv("GOOGLE_CUSTOM_SEARCH_CX")

INPUT_FILE = Path(".tmp/companies_enriched.json")
OUTPUT_FILE = Path(".tmp/companies_with_email.json")
DOMAIN_CACHE_FILE = Path(".tmp/domain_cache.json")

SMTP_TIMEOUT = 5        # seconds per SMTP connection attempt
GOOGLE_QUERY_LIMIT = 90 # warn before exceeding free tier (100/day)

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Legal title keywords for fallback when gc_name is missing
LEGAL_TITLE_KEYWORDS = [
    "general counsel", "chief legal", "legal officer", "legal counsel",
    "vice president.*legal", "senior.*legal", "attorney", "solicitor",
    "compliance officer", "corporate secretary",
]

_google_query_count = 0


def load_domain_cache():
    if DOMAIN_CACHE_FILE.exists():
        with open(DOMAIN_CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_domain_cache(cache):
    with open(DOMAIN_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def extract_domain(website):
    """Extract bare domain from a website URL, e.g. 'newmont.com'."""
    if not website:
        return None
    if not website.startswith("http"):
        website = "https://" + website
    netloc = urlparse(website).netloc
    return netloc.replace("www.", "").lower() or None


def generate_email_candidates(first_name, last_name, domain):
    """Generate common corporate email pattern candidates."""
    f = first_name.lower().strip()
    l = last_name.lower().strip()
    return [
        f"{f}.{l}@{domain}",        # john.smith@domain.com
        f"{f[0]}{l}@{domain}",      # jsmith@domain.com
        f"{f}@{domain}",            # john@domain.com
        f"{f[0]}.{l}@{domain}",     # j.smith@domain.com
        f"{l}{f[0]}@{domain}",      # smithj@domain.com
        f"{l}.{f}@{domain}",        # smith.john@domain.com
    ]


def smtp_vrfy(email):
    """
    Attempt SMTP VRFY on the email's domain mail server.
    Returns:
      "exists"       — server confirmed address (250)
      "not_found"    — server denied address (550, 551, 553)
      "unsupported"  — VRFY not supported (502, 252)
      "inconclusive" — timeout, connection refused, or other error
    """
    domain = email.split("@")[1]
    try:
        mx_host = domain  # simplified: try domain directly as MX
        with smtplib.SMTP(mx_host, 25, timeout=SMTP_TIMEOUT) as smtp:
            smtp.ehlo_or_helo_if_needed()
            code, _ = smtp.verify(email)
            if code == 250:
                return "exists"
            elif code in (550, 551, 553):
                return "not_found"
            elif code in (502, 252):
                return "unsupported"
            else:
                return "inconclusive"
    except (socket.timeout, ConnectionRefusedError, OSError):
        return "inconclusive"
    except smtplib.SMTPException:
        return "unsupported"
    except Exception:
        return "inconclusive"


def strategy_domain_pattern(first_name, last_name, domain, domain_cache):
    """
    Strategy 1: Generate email candidates and validate via SMTP VRFY.
    Returns (email, confidence) or (None, None).
    """
    if not first_name or not last_name or not domain:
        return None, None

    # Check domain cache for a known-working pattern
    if domain in domain_cache:
        pattern = domain_cache[domain]
        f = first_name.lower().strip()
        l = last_name.lower().strip()
        try:
            email = pattern.replace("{first}", f).replace("{last}", l).replace(
                "{f}", f[0]).replace("{l}", l[0])
            return email, "unverified_guess"
        except Exception:
            pass

    candidates = generate_email_candidates(first_name, last_name, domain)
    vrfy_unsupported = False

    for candidate in candidates:
        result = smtp_vrfy(candidate)
        if result == "exists":
            # Cache the pattern that worked
            f = first_name.lower().strip()
            l = last_name.lower().strip()
            pattern_str = candidate.replace(f, "{first}").replace(l, "{last}")
            domain_cache[domain] = pattern_str
            save_domain_cache(domain_cache)
            return candidate, "high"
        elif result == "not_found":
            continue
        elif result in ("unsupported", "inconclusive"):
            vrfy_unsupported = True
            break  # No point trying more if server doesn't support VRFY

    if vrfy_unsupported:
        # Return best-guess (first pattern) as unverified
        return candidates[0], "unverified_guess"

    return None, None


def google_search_email(gc_name, company_name, domain):
    """
    Strategy 2: Search Google for the GC's email in press releases and bios.
    Returns (email, confidence) or (None, None).
    """
    global _google_query_count

    if not GOOGLE_API_KEY or not GOOGLE_CX:
        return None, None

    if _google_query_count >= GOOGLE_QUERY_LIMIT:
        print(f"  WARNING: Google Search quota limit ({GOOGLE_QUERY_LIMIT}) reached. Stopping search.")
        return None, None

    query = f'"{gc_name}" "{company_name}" email'
    url = "https://www.googleapis.com/customsearch/v1"
    params = {"key": GOOGLE_API_KEY, "cx": GOOGLE_CX, "q": query, "num": 10}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        _google_query_count += 1
        items = resp.json().get("items", [])
    except requests.RequestException as e:
        print(f"    Google Search error: {e}")
        return None, None

    for item in items:
        text = item.get("snippet", "") + " " + item.get("link", "")
        for match in EMAIL_REGEX.finditer(text):
            email = match.group().lower()
            if domain and domain in email:
                return email, "high"
            elif "@" in email and not any(bad in email for bad in ["noreply", "example"]):
                return email, "medium"

    return None, None


def extract_email_from_sec_text(company):
    """
    Strategy 3: Check the 10-K cover page text (already stored) for a domain email.
    Returns (email, confidence) or (None, None).
    """
    domain = extract_domain(company.get("website"))
    # Look in any text fields we have for an email matching the domain
    fields_to_check = [
        company.get("sec_source_url") or "",
        str(company.get("jurisdictions") or ""),
    ]

    # Check contact_emails_found from website scraping
    contact_emails = company.get("contact_emails_found") or []
    for email in contact_emails:
        if domain and domain in email:
            return email, "medium"

    for text in fields_to_check:
        for match in EMAIL_REGEX.finditer(text):
            email = match.group().lower()
            if domain and domain in email:
                return email, "medium"

    return None, None


def build_linkedin_search_url(name, company_name):
    """Strategy 4: Build a LinkedIn people search URL for manual follow-up."""
    query = f"{name} {company_name}"
    encoded = quote_plus(query)
    return f"https://www.linkedin.com/search/results/people/?keywords={encoded}"


def parse_name(full_name):
    """Split a full name into first and last. Returns (first, last) or (None, None)."""
    if not full_name:
        return None, None
    parts = full_name.strip().split()
    if len(parts) < 2:
        return parts[0], parts[0]
    return parts[0], parts[-1]


def find_fallback_legal_contact(company):
    """
    If gc_name is null, look for any person in the company data whose title
    suggests a legal role. Returns (name, title) or (None, None).
    """
    pattern = re.compile("|".join(LEGAL_TITLE_KEYWORDS), re.IGNORECASE)

    # Check if there's a stored ceo_title that might be legal (edge case)
    for field_name, field_title in [
        ("ceo_name", "ceo_title"),
    ]:
        title = company.get(field_title) or ""
        if pattern.search(title):
            return company.get(field_name), title

    return None, None


def process_company(company, domain_cache):
    """Run email hunt cascade for one company. Returns updated dict."""
    # Determine GC contact
    gc_name = company.get("gc_name")
    gc_title = company.get("gc_title") or ""

    if not gc_name:
        # Try fallback: look for any legal title
        gc_name, gc_title = find_fallback_legal_contact(company)
        if gc_name:
            company["gc_name"] = gc_name
            company["gc_title"] = gc_title
        else:
            company["gc_search_needed"] = True
            company["gc_email"] = None
            company["email_confidence"] = "not_found"
            company["linkedin_search_url"] = build_linkedin_search_url(
                "", company.get("name") or company.get("long_name") or ""
            )
            return company

    domain = extract_domain(company.get("website"))
    first_name, last_name = parse_name(gc_name)
    company_name = company.get("name") or company.get("long_name") or ""

    # Always build LinkedIn URL regardless of email outcome
    company["linkedin_search_url"] = build_linkedin_search_url(gc_name, company_name)

    # Strategy 1: Domain pattern + SMTP VRFY
    email, confidence = strategy_domain_pattern(first_name, last_name, domain, domain_cache)
    if email and confidence == "high":
        company["gc_email"] = email
        company["email_confidence"] = confidence
        company["email_strategy_used"] = "smtp_vrfy"
        return company

    # Strategy 2: Google Custom Search
    email2, confidence2 = google_search_email(gc_name, company_name, domain)
    if email2:
        company["gc_email"] = email2
        company["email_confidence"] = confidence2
        company["email_strategy_used"] = "google_search"
        return company

    # Strategy 3: SEC filing / website contact page email
    email3, confidence3 = extract_email_from_sec_text(company)
    if email3:
        company["gc_email"] = email3
        company["email_confidence"] = confidence3
        company["email_strategy_used"] = "sec_or_website"
        return company

    # Strategy 1 fallback: use unverified domain guess if we have one
    if email and confidence == "unverified_guess":
        company["gc_email"] = email
        company["email_confidence"] = "unverified_guess"
        company["email_strategy_used"] = "domain_pattern_guess"
        return company

    # Nothing found
    company["gc_email"] = None
    company["email_confidence"] = "not_found"
    company["email_strategy_used"] = None

    return company


def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run scrape_company_website.py first.")
        return

    with open(INPUT_FILE) as f:
        companies = json.load(f)

    print(f"=== Phase 5: Find General Counsel Email ===\n")
    print(f"Loaded {len(companies)} companies from {INPUT_FILE}")

    if not GOOGLE_API_KEY:
        print("NOTE: GOOGLE_CUSTOM_SEARCH_API_KEY not set — Google Search strategy disabled.")

    domain_cache = load_domain_cache()

    # Checkpoint/resume
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)
        done_tickers = {
            (c.get("ticker") or "").upper()
            for c in existing
            if "email_confidence" in c
        }
        print(f"Resuming: {len(done_tickers)} already processed.")
    else:
        existing = []
        done_tickers = set()

    results = list(existing)
    existing_by_ticker = {
        (c.get("ticker") or "").upper(): i
        for i, c in enumerate(results)
        if c.get("ticker")
    }

    to_process = [
        c for c in companies
        if (c.get("ticker") or "").upper() not in done_tickers
    ]
    print(f"Companies to process: {len(to_process)}\n")

    for i, company in enumerate(to_process):
        ticker = (company.get("ticker") or "NO_TICKER").upper()
        gc = company.get("gc_name") or "GC unknown"
        print(f"  [{i+1}/{len(to_process)}] {ticker} — GC: {gc}")

        enriched = process_company(company, domain_cache)

        confidence = enriched.get("email_confidence", "")
        email = enriched.get("gc_email", "")
        print(f"    Email: {email or 'not found'} [{confidence}]")

        key = (enriched.get("ticker") or "").upper()
        if key in existing_by_ticker:
            results[existing_by_ticker[key]] = enriched
        else:
            results.append(enriched)

        with open(OUTPUT_FILE, "w") as f:
            json.dump(results, f, indent=2)

        time.sleep(0.5)

    # Summary
    high = sum(1 for c in results if c.get("email_confidence") == "high")
    guessed = sum(1 for c in results if c.get("email_confidence") == "unverified_guess")
    not_found = sum(1 for c in results if c.get("email_confidence") == "not_found")
    needs_gc = sum(1 for c in results if c.get("gc_search_needed"))

    print(f"\nDone. {len(results)} total records.")
    print(f"  Email found (high confidence): {high}")
    print(f"  Email guessed (unverified):    {guessed}")
    print(f"  Email not found:               {not_found}")
    print(f"  GC name unknown (manual review needed): {needs_gc}")
    print(f"\nTotal Google Search queries used this session: {_google_query_count}")
    print(f"\nOutput written to {OUTPUT_FILE}")
    print("Next step: run tools/push_to_google_sheets.py")

    if needs_gc > 0:
        print(f"\n{'='*60}")
        print(f"ACTION REQUIRED: {needs_gc} companies have no General Counsel identified.")
        print("LinkedIn search URLs have been populated for manual follow-up.")
        print("Search for these in the Google Sheet — look for gc_search_needed in the Notes column.")


if __name__ == "__main__":
    main()
