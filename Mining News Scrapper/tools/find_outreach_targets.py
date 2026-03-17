"""
tools/find_outreach_targets.py

Analyzes this week's mining news to identify companies worth contacting for
international arbitration early engagement. Finds GC/legal/C-suite contacts.

Steps:
  1. Read news_articles.json
  2. GPT-4o identifies 2-3 companies in dispute or pre-dispute situations
  3. For each company: Google Custom Search + website scraping for contacts
  4. Output outreach_targets.json

Input:   .tmp/news_articles.json
Output:  .tmp/outreach_targets.json

Dispute signals GPT-4o looks for:
  ACTIVE DISPUTES:
  - Arbitration claim already filed (ICSID, ICC, LCIA, UNCITRAL, SCC, etc.)
  - Investment treaty / BIT claim filed against a host government
  - Court proceedings initiated against a state or state entity
  PRE-DISPUTE SIGNALS:
  - Permit/concession revocation or suspension by government
  - Expropriation, nationalization, or forced renegotiation
  - Regulatory enforcement actions or fines
  - Investment treaty violations or BIT concerns
  - Government-investor contract disputes
  - Force majeure or project suspension orders
  - Environmental enforcement shutting down operations
  - Indigenous/community rights disputes with legal implications
  - Joint venture partner disputes
  - Host country rule-of-law deterioration affecting mining assets
"""

import json
import os
import re
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv()

PROJECT_DIR = Path(__file__).parent.parent
ROOT_DIR = PROJECT_DIR.parent
TMP_DIR = PROJECT_DIR / ".tmp"
INPUT_FILE  = TMP_DIR / "news_articles.json"
OUTPUT_FILE = TMP_DIR / "outreach_targets.json"

REQUEST_TIMEOUT = 10
MAX_TARGETS = 5
RATE_LIMIT_SLEEP = 60

SESSION_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

LEADERSHIP_PATHS = [
    "/leadership", "/management", "/team", "/our-team",
    "/about/leadership", "/about/management", "/about/team",
    "/company/leadership", "/company/team",
    "/about-us/leadership", "/about-us/team",
    "/about", "/about-us",
]

CONTACT_PATHS = ["/contact", "/contact-us", "/contacts", "/about/contact"]

# ---------------------------------------------------------------------------
# GPT-4o: identify dispute targets
# ---------------------------------------------------------------------------

IDENTIFY_SYSTEM = """You are an expert in international arbitration and mining law.
Your task is to analyze mining news articles and identify companies that represent
strong early-engagement opportunities for an international arbitration practitioner."""

def build_identify_prompt(articles):
    """Build prompt asking GPT-4o to find dispute/pre-dispute targets."""
    lines = [
        "Analyze the following mining news articles from the past week. "
        f"Identify up to {MAX_TARGETS} compelling companies for outreach by an international "
        "arbitration practitioner. Include BOTH companies already in active arbitration AND "
        "companies showing pre-dispute signals — both represent engagement opportunities.\n\n"

        "INCLUDE companies showing ANY of these signals:\n\n"

        "ACTIVE DISPUTES (recently filed — counsel, co-counsel, expert, or claims support needed):\n"
        "- Arbitration claim filed (ICSID, ICC, LCIA, UNCITRAL, SCC, or any tribunal)\n"
        "- Investment treaty claim filed (BIT, ECT, NAFTA/CUSMA, or other IIA)\n"
        "- Court proceedings initiated against a host government\n\n"

        "PRE-DISPUTE SIGNALS (company likely needs counsel before filing):\n"
        "- Government permit/concession revocation, suspension, or non-renewal\n"
        "- Expropriation, nationalization, or forced renegotiation of mining rights\n"
        "- Regulatory enforcement actions (fines, shutdowns, sanctions)\n"
        "- BIT / investment treaty violations or host-country rule-of-law concerns\n"
        "- Government-investor contract disputes or unilateral contract changes\n"
        "- Force majeure declarations or government-ordered project suspensions\n"
        "- Environmental enforcement shutting down or threatening operations\n"
        "- Indigenous/community rights disputes with potential legal consequences\n"
        "- Joint venture partner disputes with arbitration clauses\n"
        "- Political instability threatening existing mining contracts\n\n"

        'Respond with a JSON object in this EXACT format (always use the "targets" key):\n'
        '{"targets": [\n'
        "  {\n"
        '    "company_name": "Exact company name",\n'
        '    "ticker": "Stock ticker if known, else null",\n'
        '    "jurisdiction": "Country where the dispute/issue is occurring",\n'
        '    "dispute_type": "One of: active_arbitration | permit_revocation | expropriation | enforcement_action | treaty_concern | contract_dispute | force_majeure | environmental | community_rights | jv_dispute | political_risk | other",\n'
        '    "situation_summary": "2-3 sentences describing the specific situation, naming the tribunal/treaty/decree where known",\n'
        '    "engagement_rationale": "1-2 sentences on why an arbitration practitioner should reach out NOW (e.g. counsel needed, co-counsel opportunity, claims support, expert witnesses)",\n'
        '    "urgency": "high | medium | low",\n'
        '    "source_headline": "The exact article headline that flagged this"\n'
        "  }\n"
        "]}\n\n"
        f"Return up to {MAX_TARGETS} targets. If fewer companies show clear signals, return only those. "
        'If NO companies show any relevant signals, return {"targets": []}.\n\n'
        "ARTICLES:\n"
    ]

    # Add articles, capped to keep prompt manageable
    total_chars = sum(len(l) for l in lines)
    for art in articles:
        entry = f"\n[{art['source']}] {art['title']}\n"
        if art.get("snippet"):
            entry += f"{art['snippet'][:400]}\n"
        if total_chars + len(entry) > 50_000:
            break
        lines.append(entry)
        total_chars += len(entry)

    return "".join(lines)


def identify_targets(client, articles):
    """Call GPT-4o to identify dispute/pre-dispute companies. Returns list of dicts."""
    prompt = build_identify_prompt(articles)

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": IDENTIFY_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=1500,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            parsed = json.loads(raw)
            # Unwrap {"targets": [...]} or any dict-wrapped list
            if isinstance(parsed, dict):
                # Check for a list value (e.g. {"targets": [...]})
                for v in parsed.values():
                    if isinstance(v, list):
                        return v
                # Single target returned as a flat dict — wrap it
                if "company_name" in parsed:
                    return [parsed]
                return []
            return parsed if isinstance(parsed, list) else []
        except RateLimitError:
            if attempt == 0:
                print(f"    GPT-4o rate limit — waiting {RATE_LIMIT_SLEEP}s...")
                time.sleep(RATE_LIMIT_SLEEP)
            else:
                raise
        except Exception as e:
            print(f"    GPT-4o error identifying targets: {e}")
            return []
    return []


# ---------------------------------------------------------------------------
# Contact search: Google Custom Search
# ---------------------------------------------------------------------------

def google_search(query, api_key, cx, num=5):
    """Run a Google Custom Search query. Returns list of result dicts."""
    url = "https://www.googleapis.com/customsearch/v1"
    params = {"key": api_key, "cx": cx, "q": query, "num": num}
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("items", [])
    except Exception:
        return []


def extract_company_website(company_name, api_key, cx):
    """Find the company's official website via Google Search."""
    results = google_search(f'"{company_name}" mining official website', api_key, cx, num=3)
    for r in results:
        link = r.get("link", "")
        # Prefer .com/.ca/.au domains that look like company homepages
        if link and not any(skip in link for skip in [
            "linkedin", "twitter", "facebook", "reuters", "bloomberg",
            "mining.com", "northernminer", "wikipedia", "yahoo", "google"
        ]):
            parsed = urlparse(link)
            return f"{parsed.scheme}://{parsed.netloc}"
    return None


def search_gc_contact(company_name, api_key, cx):
    """
    Search Google for GC/CLO/legal team contact at the company.
    Returns dict with name, title, email (any may be None).
    """
    contact = {"name": None, "title": None, "email": None, "linkedin_url": None, "source": None}

    queries = [
        f'"{company_name}" "general counsel" OR "chief legal officer" mining',
        f'"{company_name}" "general counsel" email',
        f'"{company_name}" CLO OR GC mining contact',
    ]

    for query in queries:
        results = google_search(query, api_key, cx, num=5)
        for r in results:
            snippet = r.get("snippet", "") + " " + r.get("title", "")
            # Look for email in snippet
            email_match = EMAIL_REGEX.search(snippet)
            if email_match:
                contact["email"] = email_match.group().lower()
                contact["source"] = r.get("link", "")

            # Look for name patterns: "Name, General Counsel"
            name_match = re.search(
                r"([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)"
                r"[,\s]+(?:General Counsel|Chief Legal Officer|CLO|GC)",
                snippet, re.IGNORECASE
            )
            if name_match and not contact["name"]:
                contact["name"] = name_match.group(1).strip()
                contact["title"] = "General Counsel"
                contact["source"] = r.get("link", "")

            # LinkedIn profile link
            link = r.get("link", "")
            if "linkedin.com/in/" in link and not contact["linkedin_url"]:
                contact["linkedin_url"] = link

        time.sleep(0.5)

    return contact


def search_csuite_contact(company_name, api_key, cx):
    """
    Search Google for CEO/President contact at the company.
    Returns dict with name, title, email.
    """
    contact = {"name": None, "title": None, "email": None, "linkedin_url": None, "source": None}

    queries = [
        f'"{company_name}" CEO OR President mining contact',
        f'"{company_name}" "chief executive" email',
    ]

    for query in queries:
        results = google_search(query, api_key, cx, num=5)
        for r in results:
            snippet = r.get("snippet", "") + " " + r.get("title", "")

            email_match = EMAIL_REGEX.search(snippet)
            if email_match:
                contact["email"] = email_match.group().lower()
                contact["source"] = r.get("link", "")

            name_match = re.search(
                r"([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)"
                r"[,\s]+(?:CEO|Chief Executive|President)",
                snippet, re.IGNORECASE
            )
            if name_match and not contact["name"]:
                contact["name"] = name_match.group(1).strip()
                contact["title"] = "CEO"
                contact["source"] = r.get("link", "")

            link = r.get("link", "")
            if "linkedin.com/in/" in link and not contact["linkedin_url"]:
                contact["linkedin_url"] = link

        time.sleep(0.5)

    return contact


# ---------------------------------------------------------------------------
# Website scraping for leadership contacts
# ---------------------------------------------------------------------------

def is_allowed_by_robots(base_url, path):
    try:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{base_url}/robots.txt")
        rp.read()
        return rp.can_fetch(SESSION_HEADERS["User-Agent"], f"{base_url}{path}")
    except Exception:
        return True


def fetch_page(url):
    for attempt in range(2):
        try:
            resp = requests.get(
                url, headers=SESSION_HEADERS, timeout=REQUEST_TIMEOUT,
                allow_redirects=True, stream=True
            )
            if resp.status_code != 200:
                return None
            raw = resp.raw.read(1 * 1024 * 1024, decode_content=True)
            return BeautifulSoup(raw, "lxml")
        except Exception:
            if attempt == 0:
                time.sleep(2)
    return None


def scrape_leadership_from_website(base_url):
    """
    Scrape company website leadership page for GC/CEO names and emails.
    Returns dict: {gc_name, gc_title, ceo_name, ceo_title, emails}
    """
    result = {"gc_name": None, "gc_title": None, "ceo_name": None, "ceo_title": None, "emails": []}

    for path in LEADERSHIP_PATHS:
        if not is_allowed_by_robots(base_url, path):
            continue
        soup = fetch_page(f"{base_url}{path}")
        if not soup:
            continue

        text = soup.get_text(separator=" ", strip=True)

        # Find GC
        gc_match = re.search(
            r"([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)"
            r"[^.]{0,60}"
            r"(?:General Counsel|Chief Legal Officer|CLO|VP Legal|VP[\s,]+Legal)",
            text, re.IGNORECASE
        )
        if gc_match and not result["gc_name"]:
            result["gc_name"] = gc_match.group(1).strip()
            result["gc_title"] = "General Counsel"

        # Find CEO
        ceo_match = re.search(
            r"([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)"
            r"[^.]{0,60}"
            r"(?:Chief Executive|CEO|\bPresident\b)",
            text, re.IGNORECASE
        )
        if ceo_match and not result["ceo_name"]:
            result["ceo_name"] = ceo_match.group(1).strip()
            result["ceo_title"] = "CEO"

        if result["gc_name"] or result["ceo_name"]:
            break

        time.sleep(1)

    # Also check contact pages for emails
    for path in CONTACT_PATHS:
        if not is_allowed_by_robots(base_url, path):
            continue
        soup = fetch_page(f"{base_url}{path}")
        if not soup:
            continue
        text = soup.get_text()
        for match in EMAIL_REGEX.finditer(text):
            email = match.group().lower()
            if not any(bad in email for bad in ["noreply", "no-reply", "example.com"]):
                if email not in result["emails"]:
                    result["emails"].append(email)
        if result["emails"]:
            break
        time.sleep(1)

    return result


# ---------------------------------------------------------------------------
# Main contact lookup
# ---------------------------------------------------------------------------

def find_contacts(company_name, api_key, cx):
    """
    Multi-strategy contact discovery for a company.
    Returns structured contact dict.
    """
    print(f"    Searching contacts for: {company_name}")
    contacts = {
        "gc": {"name": None, "title": None, "email": None, "linkedin_url": None},
        "ceo": {"name": None, "title": None, "email": None, "linkedin_url": None},
        "website": None,
        "contact_emails": [],
    }

    if not api_key or not cx:
        print("    WARNING: GOOGLE_CUSTOM_SEARCH_API_KEY or CX not set — skipping contact search")
        return contacts

    # 1. Find company website
    website = extract_company_website(company_name, api_key, cx)
    contacts["website"] = website
    time.sleep(0.5)

    # 2. Search for GC
    gc = search_gc_contact(company_name, api_key, cx)
    if gc["name"] or gc["email"]:
        contacts["gc"] = gc

    # 3. Search for CEO (fallback)
    ceo = search_csuite_contact(company_name, api_key, cx)
    if ceo["name"] or ceo["email"]:
        contacts["ceo"] = ceo

    # 4. Scrape company website if found
    if website:
        print(f"    Scraping website: {website}")
        scraped = scrape_leadership_from_website(website)
        if scraped["gc_name"] and not contacts["gc"]["name"]:
            contacts["gc"]["name"] = scraped["gc_name"]
            contacts["gc"]["title"] = scraped["gc_title"]
        if scraped["ceo_name"] and not contacts["ceo"]["name"]:
            contacts["ceo"]["name"] = scraped["ceo_name"]
            contacts["ceo"]["title"] = scraped["ceo_title"]
        if scraped["emails"]:
            contacts["contact_emails"] = scraped["emails"][:3]

    return contacts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run fetch_mining_news.py first.")
        return

    with open(INPUT_FILE) as f:
        articles = json.load(f)

    print("=" * 60)
    print("  Step 3: Find Outreach Targets")
    print(f"  Articles: {len(articles)}")
    print("=" * 60)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set.")
        return

    google_key = os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
    google_cx  = os.getenv("GOOGLE_CUSTOM_SEARCH_CX")

    client = OpenAI(api_key=api_key)

    # Step 1: GPT-4o identifies targets
    print("\n  Identifying dispute/pre-dispute targets via GPT-4o...")
    targets = identify_targets(client, articles)
    print(f"  Found {len(targets)} potential target(s)")

    if not targets:
        print("  No dispute signals found this week — writing empty output")
        with open(OUTPUT_FILE, "w") as f:
            json.dump([], f, indent=2)
        return

    # Step 2: Find contacts for each target
    enriched = []
    for i, target in enumerate(targets[:MAX_TARGETS]):
        name = target.get("company_name", "Unknown")
        print(f"\n  [{i+1}/{min(len(targets), MAX_TARGETS)}] {name}")
        print(f"    Dispute type: {target.get('dispute_type', 'unknown')}")
        print(f"    Jurisdiction: {target.get('jurisdiction', 'unknown')}")

        contacts = find_contacts(name, google_key, google_cx)
        target["contacts"] = contacts

        # Build human-readable contact summary
        contact_lines = []
        gc = contacts.get("gc", {})
        ceo = contacts.get("ceo", {})

        if gc.get("name"):
            line = f"{gc['name']}"
            if gc.get("title"): line += f", {gc['title']}"
            if gc.get("email"): line += f" — {gc['email']}"
            if gc.get("linkedin_url") and not gc.get("email"):
                line += f" — {gc['linkedin_url']}"
            contact_lines.append(line)

        if ceo.get("name"):
            line = f"{ceo['name']}"
            if ceo.get("title"): line += f", {ceo['title']}"
            if ceo.get("email"): line += f" — {ceo['email']}"
            if ceo.get("linkedin_url") and not ceo.get("email"):
                line += f" — {ceo['linkedin_url']}"
            contact_lines.append(line)

        if contacts.get("contact_emails"):
            contact_lines.append(f"General contact: {', '.join(contacts['contact_emails'])}")

        if not contact_lines:
            contact_lines.append("No public contact information found — manual research recommended")

        if contacts.get("website"):
            contact_lines.append(f"Website: {contacts['website']}")

        target["contact_summary"] = contact_lines
        enriched.append(target)

        gc_found = "✓" if gc.get("name") or gc.get("email") else "—"
        ceo_found = "✓" if ceo.get("name") or ceo.get("email") else "—"
        print(f"    GC found: {gc_found}  CEO found: {ceo_found}")

        time.sleep(1)  # Pause between companies

    with open(OUTPUT_FILE, "w") as f:
        json.dump(enriched, f, indent=2)

    print(f"\n  {len(enriched)} outreach target(s) written to {OUTPUT_FILE}")
    print("Next step: run tools/send_email_digest.py")


if __name__ == "__main__":
    main()
