"""
tools/scrape_company_website.py

Scrapes mining company websites to fill in data missing after EDGAR extraction:
  - CEO and General Counsel names (from /leadership, /team, /management pages)
  - Email addresses visible on /contact pages
  - Projects and jurisdictions (from /operations, /projects pages)

Rules:
  - Respects robots.txt — never scrapes disallowed paths
  - Never overwrites fields already populated by SEC extraction
  - Gracefully handles JS-heavy sites (no data returned, not an error)
  - 10-second timeout + 1 retry per request

Input:   .tmp/companies_leadership.json
Output:  .tmp/companies_enriched.json
"""

import json
import re
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

INPUT_FILE = Path(".tmp/companies_leadership.json")
OUTPUT_FILE = Path(".tmp/companies_enriched.json")

REQUEST_TIMEOUT = 10
RETRY_DELAY = 5
MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2MB cap — prevents hanging on huge downloads
SESSION_HEADERS = {
    "User-Agent": "MiningResearchBot/1.0 (research purposes; contact@example.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Leadership page candidate paths (tried in order)
LEADERSHIP_PATHS = [
    "/leadership", "/management", "/team", "/our-team",
    "/about/leadership", "/about/management", "/about/team",
    "/company/leadership", "/company/team",
    "/about-us/leadership", "/about-us/team",
    "/about", "/about-us",
]

# Contact page candidate paths
CONTACT_PATHS = ["/contact", "/contact-us", "/contacts", "/about/contact"]

# Operations/project page candidate paths
OPERATIONS_PATHS = [
    "/operations", "/projects", "/portfolio",
    "/assets", "/properties", "/our-projects", "/our-operations",
    "/mining-operations", "/mines",
]

# Reference list of mining-relevant countries and regions
MINING_COUNTRIES = [
    "United States", "USA", "Canada", "Australia", "Mexico", "Chile",
    "Peru", "Brazil", "Argentina", "Colombia", "Bolivia", "Ecuador",
    "South Africa", "Ghana", "Tanzania", "Democratic Republic of Congo",
    "DRC", "Congo", "Zambia", "Zimbabwe", "Botswana", "Mali",
    "Burkina Faso", "Guinea", "Senegal", "Ivory Coast",
    "Indonesia", "Philippines", "Papua New Guinea", "Mongolia",
    "Kazakhstan", "Kyrgyzstan", "Uzbekistan", "Russia",
    "Finland", "Sweden", "Norway", "Greenland",
    "Nevada", "Alaska", "Arizona", "Colorado", "Montana", "Utah",
    "Ontario", "British Columbia", "Quebec", "Saskatchewan", "Manitoba",
    "Western Australia", "Queensland", "New South Wales", "Northern Territory",
]

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def get_base_url(website):
    """Normalize website URL to base (scheme + netloc)."""
    if not website:
        return None
    if not website.startswith("http"):
        website = "https://" + website
    parsed = urlparse(website)
    return f"{parsed.scheme}://{parsed.netloc}"


def is_allowed_by_robots(base_url, path):
    """Check robots.txt to see if the path is allowed."""
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
        return True  # if we can't read robots.txt, assume allowed


def fetch_page(url):
    """
    Fetch a URL with timeout and one retry.
    Returns BeautifulSoup object or None.
    Streams response and caps at MAX_RESPONSE_BYTES to avoid hanging on huge downloads.
    """
    for attempt in range(2):
        try:
            resp = requests.get(
                url,
                headers=SESSION_HEADERS,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
                stream=True,
            )
            if resp.status_code != 200:
                return None
            raw = resp.raw.read(MAX_RESPONSE_BYTES, decode_content=True)
            return BeautifulSoup(raw, "lxml")
        except (requests.ConnectionError, requests.Timeout, requests.TooManyRedirects):
            if attempt == 0:
                time.sleep(RETRY_DELAY)
        except Exception:
            return None
    return None


def try_paths(base_url, paths):
    """
    Try a list of URL paths until one returns a 200 response.
    Returns (BeautifulSoup, url) or (None, None).
    """
    for path in paths:
        if not is_allowed_by_robots(base_url, path):
            continue
        url = f"{base_url}{path}"
        soup = fetch_page(url)
        if soup:
            return soup, url
    return None, None


def extract_names_and_titles(soup):
    """
    Extract (name, title) pairs from a leadership page.
    Returns list of dicts: [{name, title}, ...]
    """
    results = []
    if not soup:
        return results

    # Strategy 1: Look for structured name+title patterns in common elements
    # Many leadership pages use h3/h4 for name and p/span for title
    candidate_containers = soup.find_all(
        ["div", "article", "section", "li"],
        class_=re.compile(r"(person|member|executive|officer|leader|team|bio|card)", re.I),
    )

    for container in candidate_containers:
        name_el = container.find(
            re.compile(r"h[2-5]|strong|b"),
            class_=re.compile(r"(name|title|heading)", re.I),
        ) or container.find(re.compile(r"h[2-5]"))

        title_el = container.find(
            ["p", "span", "div"],
            class_=re.compile(r"(title|role|position|job)", re.I),
        )

        name = name_el.get_text(strip=True) if name_el else ""
        title = title_el.get_text(strip=True) if title_el else ""

        if name and len(name.split()) >= 2:
            results.append({"name": name, "title": title})

    if results:
        return results

    # Strategy 2: Parse all h3/h4 tags — assume they are names, next sibling is title
    for heading in soup.find_all(["h3", "h4"]):
        name = heading.get_text(strip=True)
        if len(name.split()) < 2 or len(name.split()) > 5:
            continue
        # Look for title in next sibling or child p
        sibling = heading.find_next_sibling(["p", "span", "div"])
        title = sibling.get_text(strip=True)[:100] if sibling else ""
        if name:
            results.append({"name": name, "title": title})

    return results


def find_executive_by_title(people, title_keywords):
    """
    Given a list of {name, title} dicts, return the one whose title
    matches any of the title_keywords (case-insensitive).
    Returns (name, title) or (None, None).
    """
    keywords_pattern = re.compile("|".join(title_keywords), re.IGNORECASE)
    for person in people:
        if keywords_pattern.search(person.get("title", "")):
            return person["name"], person["title"]
    return None, None


def extract_emails_from_soup(soup):
    """Extract all email addresses visible on a page."""
    emails = set()
    if not soup:
        return emails

    # mailto: links
    for tag in soup.find_all("a", href=re.compile(r"^mailto:", re.I)):
        href = tag["href"]
        email = href.replace("mailto:", "").split("?")[0].strip().lower()
        if EMAIL_REGEX.match(email):
            emails.add(email)

    # Plain text emails
    text = soup.get_text()
    for match in EMAIL_REGEX.finditer(text):
        emails.add(match.group().lower())

    # Filter out image/tracking/noreply addresses
    filtered = {
        e for e in emails
        if not any(bad in e for bad in ["noreply", "no-reply", "example.com", ".png", ".jpg"])
    }
    return filtered


def extract_projects_from_soup(soup):
    """
    Extract project names and countries from an operations/projects page.
    Returns (projects_list, countries_list).
    """
    projects = []
    countries = []
    if not soup:
        return projects, countries

    text = soup.get_text(separator=" ", strip=True)

    # Mine/project name patterns
    mine_pattern = re.compile(
        r"([A-Z][A-Za-z\s]{2,30})\s+(?:mine|project|deposit|property|operation|complex)\b",
        re.IGNORECASE,
    )
    for m in mine_pattern.finditer(text):
        name = m.group(1).strip()
        if (
            len(name.split()) <= 5
            and name.lower().split()[0] not in {"the", "a", "an", "our", "its"}
        ):
            if name not in projects:
                projects.append(name)
        if len(projects) >= 10:
            break

    # Country mentions
    for country in MINING_COUNTRIES:
        if re.search(r'\b' + re.escape(country) + r'\b', text, re.IGNORECASE):
            if country not in countries:
                countries.append(country)

    return projects[:10], countries


def process_company(company):
    """Scrape website for one company and fill in missing fields."""
    website = company.get("website")
    base_url = get_base_url(website)

    if not base_url:
        return company

    # Only scrape if there's missing data
    needs_ceo = not company.get("ceo_name")
    needs_gc = not company.get("gc_name")
    needs_email = not company.get("contact_email")
    needs_projects = not company.get("projects")

    if not any([needs_ceo, needs_gc, needs_email, needs_projects]):
        return company

    scraped_anything = False

    # Leadership page
    if needs_ceo or needs_gc:
        soup, url = try_paths(base_url, LEADERSHIP_PATHS)
        if soup:
            people = extract_names_and_titles(soup)
            if needs_ceo:
                name, title = find_executive_by_title(
                    people,
                    ["chief executive", r"\bCEO\b", "president"],
                )
                if name:
                    company["ceo_name"] = name
                    company["ceo_title"] = title
                    scraped_anything = True

            if needs_gc:
                name, title = find_executive_by_title(
                    people,
                    ["general counsel", "chief legal", r"\bCLO\b", "legal officer"],
                )
                if name:
                    company["gc_name"] = name
                    company["gc_title"] = title
                    scraped_anything = True
        time.sleep(1)

    # Contact page — look for emails
    if needs_email:
        soup, url = try_paths(base_url, CONTACT_PATHS)
        if soup:
            emails = extract_emails_from_soup(soup)
            if emails:
                # Prefer a non-generic email; sort for determinism
                company["contact_emails_found"] = sorted(emails)
                # Pick the most relevant one (prefer legal@ or counsel@ or info@)
                preferred = next(
                    (e for e in sorted(emails) if any(
                        k in e for k in ["legal", "counsel", "gc@", "law@"]
                    )),
                    None,
                ) or sorted(emails)[0]
                company["contact_email"] = preferred
                scraped_anything = True
        time.sleep(1)

    # Operations/projects page
    if needs_projects:
        soup, url = try_paths(base_url, OPERATIONS_PATHS)
        if soup:
            projects, countries = extract_projects_from_soup(soup)
            if projects:
                company["projects"] = projects
                scraped_anything = True
            if countries:
                company["project_countries"] = countries
                if not company.get("jurisdictions"):
                    company["jurisdictions"] = "; ".join(countries)
                scraped_anything = True
        time.sleep(1)

    if not scraped_anything:
        company["website_unreachable"] = True

    # Track data source
    sources = company.get("data_sources") or []
    if scraped_anything and "website" not in sources:
        sources.append("website")
    company["data_sources"] = sources

    return company


def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run extract_sec_leadership.py first.")
        return

    with open(INPUT_FILE) as f:
        companies = json.load(f)

    print(f"=== Phase 4: Scrape Company Websites ===\n")
    print(f"Loaded {len(companies)} companies from {INPUT_FILE}")

    # Checkpoint/resume
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)
        done_tickers = {
            (c.get("ticker") or "").upper()
            for c in existing
            if c.get("website_unreachable") is not None
               or c.get("contact_email")
               or c.get("ceo_name")
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
        print(f"  [{i+1}/{len(to_process)}] {ticker} — {company.get('name', '')[:50]}")

        enriched = process_company(company)

        key = (enriched.get("ticker") or "").upper()
        if key in existing_by_ticker:
            results[existing_by_ticker[key]] = enriched
        else:
            results.append(enriched)

        with open(OUTPUT_FILE, "w") as f:
            json.dump(results, f, indent=2)

    with_ceo = sum(1 for c in results if c.get("ceo_name"))
    with_gc = sum(1 for c in results if c.get("gc_name"))
    with_email = sum(1 for c in results if c.get("contact_email"))
    with_projects = sum(1 for c in results if c.get("projects"))

    print(f"\nDone. {len(results)} total records.")
    print(f"  CEO found: {with_ceo}")
    print(f"  GC found: {with_gc}")
    print(f"  Contact email found: {with_email}")
    print(f"  Projects found: {with_projects}")
    print(f"\nOutput written to {OUTPUT_FILE}")
    print("Next step: run tools/find_gc_email.py")


if __name__ == "__main__":
    main()
