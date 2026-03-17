# Workflow: Mining Company Research

## Objective
Build a comprehensive Google Sheet of publicly traded mining companies. For each
company, collect: company name, ticker, exchange, CEO, General Counsel / CLO,
jurisdictions of operation, revenue, tons of ore processed, major projects and
their countries, and a best-effort email address for the senior legal contact.

---

## Required Setup (Complete Before First Run)

All of the following must be in place before any tool will work.

### 1. Fill in `.env`

```
EDGAR_USER_AGENT=Your Name your@email.com      # Required — real name and email
GOOGLE_CUSTOM_SEARCH_API_KEY=...               # Required — 100 free queries/day
GOOGLE_CUSTOM_SEARCH_CX=...                    # Required — your custom search engine ID
GOOGLE_SHEETS_ID=...                           # Required — from the spreadsheet URL
```

**EDGAR_USER_AGENT:** The SEC requires all automated scripts to identify themselves.
Format must be exactly: `"First Last email@domain.com"`. Using a fake agent will
result in IP blocks.

**Google Custom Search setup:**
1. Go to https://console.cloud.google.com — enable "Custom Search API"
2. Get an API key under APIs & Services > Credentials
3. Create a search engine at https://programmablesearchengine.google.com
   - Set "Search the entire web" to ON
   - Copy the "Search engine ID" (cx value)

### 2. Google Sheets OAuth Setup

1. Go to https://console.cloud.google.com — create a project called "Mining Research"
2. Enable "Google Sheets API" and "Google Drive API" under APIs & Services > Library
3. OAuth consent screen: External, add your email as a test user
4. Create credentials: OAuth client ID > Desktop app > Download JSON
5. Rename the downloaded file to `credentials.json` and place it in the project root
6. Create a blank Google Sheet, copy its ID from the URL, add to `.env` as `GOOGLE_SHEETS_ID`
7. First run of `push_to_google_sheets.py` will open a browser for authorization

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

---

## Execution: Run These Tools in Order

Each tool reads from a `.tmp/` file and writes to the next `.tmp/` file. All stages
support checkpoint/resume — if a tool is interrupted, re-running it picks up where
it left off.

---

### Phase 1 — Discover Mining Companies

**Tool:** `tools/discover_mining_companies.py`
**Run:** `python tools/discover_mining_companies.py`
**Output:** `.tmp/companies_raw.json`

**What it does:**
- Sweeps SEC EDGAR for companies under mining SIC codes: 1000, 1040, 1090, 1094, 1400
- Runs Google Custom Search queries to find international mining companies (TSX, ASX, LSE)
- Deduplicates by ticker symbol; EDGAR records take priority (they have CIK)

**Rate limits:**
- EDGAR: 0.12s delay between requests (SEC limit: 10 req/s)
- Google Search: 5–10 queries used here (100/day free tier)

**What to check after:**
- Open `.tmp/companies_raw.json` — should contain 200–500+ company records
- Verify a mix of US (EDGAR) and international companies are present
- If very few results: check `EDGAR_USER_AGENT` is set correctly and `GOOGLE_CUSTOM_SEARCH_API_KEY` works

---

### Phase 2 — Enrich with Financial Data (yfinance)

**Tool:** `tools/enrich_yfinance.py`
**Run:** `python tools/enrich_yfinance.py`
**Output:** `.tmp/companies_yfinance.json`

**What it does:**
- For each company with a ticker, calls Yahoo Finance to get: exchange, revenue,
  market cap, website URL, country, sector, fiscal year data

**Rate limits:**
- 2-second sleep between yfinance calls (~2,000 requests/hour max)
- For 500 companies this takes ~17 minutes — let it run

**What to check after:**
- Look for `yfinance_error: true` records — these had invalid tickers and will have
  null financial data. Small-cap and OTC-listed miners are common here.
- Revenue null for many small miners is expected — mark as "Not reported"

---

### Phase 3 — Extract Leadership from SEC 10-K Filings

**Tool:** `tools/extract_sec_leadership.py`
**Run:** `python tools/extract_sec_leadership.py`
**Output:** `.tmp/companies_leadership.json`

**What it does:**
- For each EDGAR-listed company (has a CIK), finds the most recent 10-K annual report
- Downloads the first 150KB of the primary 10-K document
- Regex-parses the "EXECUTIVE OFFICERS" section for CEO and General Counsel names
- Regex-parses "ITEM 2 PROPERTIES" for project names, countries, and ore tonnage

**Rate limits:**
- 0.15s delay between EDGAR API calls (3 calls per company = ~0.45s per company)
- For 300 EDGAR companies this takes ~2–3 minutes

**What to check after:**
- CEO found for most large/mid-cap miners; many small miners have sparse 10-Ks
- GC not found for ~20–30% of companies — expected; website scraping is next
- Non-US companies (no CIK) are passed through unchanged to Phase 4

**Known issues:**
- Some filers use XBRL-only submissions — the regex will return empty; those companies
  will be flagged as needing manual review
- If you see consistent 403 errors: verify `EDGAR_USER_AGENT` is set and uses a real
  email address

---

### Phase 4 — Scrape Company Websites

**Tool:** `tools/scrape_company_website.py`
**Run:** `python tools/scrape_company_website.py`
**Output:** `.tmp/companies_enriched.json`

**What it does:**
- For companies with missing data after Phase 3, scrapes their website:
  `/leadership`, `/team`, `/management` for CEO and GC names
  `/contact`, `/contact-us` for publicly visible email addresses
  `/operations`, `/projects`, `/portfolio` for project and country data
- Respects robots.txt — disallowed paths are skipped
- Never overwrites fields already populated by Phase 3

**Rate limits:**
- ~3 seconds per company (3 page fetches with delays)
- For 200 companies with missing data: ~10 minutes

**What to check after:**
- Many modern mining company websites use JavaScript — BeautifulSoup will get empty
  results on JS-rendered pages. These companies will have `website_unreachable: true`
  even if their site is live. This is expected and not an error.
- Contact emails found on websites are stored in `contact_emails_found` and the best
  match is in `contact_email` — this is a company-level email, not necessarily the GC's

---

### Phase 5 — Find General Counsel Email

**Tool:** `tools/find_gc_email.py`
**Run:** `python tools/find_gc_email.py`
**Output:** `.tmp/companies_with_email.json`

**What it does:**
For each company's GC/CLO (or most senior lawyer if GC not identified):

1. **Domain pattern + SMTP VRFY:** Generates 6 email candidates, validates via SMTP.
   Most corporate mail servers (Office 365, Google Workspace) disable VRFY,
   so most results will be `unverified_guess`, not `high`.
2. **Google Custom Search:** Searches for the GC's name + company + "email" in press
   releases and public bios. Each company uses 1–2 queries.
3. **SEC filing / website contacts:** Checks data already collected for domain-matching emails.
4. **LinkedIn URL (always):** Constructs a LinkedIn search URL for every company —
   stored in `linkedin_search_url` for manual follow-up regardless of whether an email
   was found.

**Rate limits (CRITICAL):**
- Google Search: 1–2 queries per company, 100/day free tier
- For 100 companies: uses 100–200 queries = **will exceed free daily quota**
- Process in batches of 30–40 companies per day to stay within free tier, OR
  purchase additional quota at $5 per 1,000 queries in Google Cloud Console
- The script warns and pauses when it approaches 90 queries/session

**What to check after:**
- `email_confidence: high` — verified via SMTP (rare with modern mail servers)
- `email_confidence: unverified_guess` — pattern guess, may bounce; verify manually
- `email_confidence: not_found` — use the `linkedin_search_url` for manual lookup
- `gc_search_needed: true` — no GC identified at all; company needs manual research

**Adding paid services later:**
- Hunter.io: Set `HUNTER_API_KEY` in `.env`, create `tools/lookup_hunter.py`
- Apollo.io: Set `APOLLO_API_KEY` in `.env`, create `tools/lookup_apollo.py`
- Proxycurl (LinkedIn): Set `PROXYCURL_API_KEY` in `.env`, create `tools/lookup_linkedin_proxycurl.py`
- Insert these as additional strategies in `find_gc_email.py` after Strategy 1

---

### Phase 6 — Push to Google Sheet

**Tool:** `tools/push_to_google_sheets.py`
**Run:** `python tools/push_to_google_sheets.py`
**Output:** Google Sheet (ID from `GOOGLE_SHEETS_ID` in `.env`)

**What it does:**
- Authenticates via OAuth2 (browser prompt on first run, automatic thereafter)
- Writes 21-column header row if the sheet is empty
- Checks existing tickers in the sheet and skips duplicates
- Appends all new records in batches of 50

**Rate limits:**
- Google Sheets API: 60 writes/minute. The script sleeps 1s between batches.

**What to check after:**
- Open the Google Sheet and verify columns A–U are populated
- Sort by col H (Email Confidence) to review all `unverified_guess` and `not_found` rows
- Filter col U (Notes / Flags) for `gc_search_needed` — these need manual LinkedIn research

---

## Edge Cases

### GC Not Found After All Phases
If `gc_search_needed: true` after Phase 5:
1. Check the `linkedin_search_url` column — open it and search manually for the company's legal team
2. Look for titles: "General Counsel", "Chief Legal Officer", "VP Legal", "Legal Counsel"
3. Take the most senior legal title present
4. If you find the contact, you can manually add them to the Google Sheet

### Non-US Companies (No EDGAR CIK)
Companies listed on TSX, ASX, or LSE without a US EDGAR filing:
- Phase 3 is skipped entirely
- Phase 4 (website) and Phase 5 (email hunt) are the only data sources for leadership
- Noted as `"SEDAR/ASX — no EDGAR data"` in the Notes column
- Future upgrade: add SEDAR+ (Canada) and ASX company announcements scraping

### Company Website Unreachable
If `website_unreachable: true`:
- Phase 4 returned no data (JS-rendered site or HTTP error)
- Phase 3 (SEC) remains the sole leadership source
- To improve coverage: add Playwright/Selenium support (requires user approval first)

### Google Search Quota Hit Mid-Run
If the script pauses with a quota warning:
- Wait until the next day (quota resets at midnight Pacific) and re-run — checkpoint
  will resume from where it left off
- Or purchase additional quota: https://console.cloud.google.com (Custom Search API)

---

## When to Stop and Ask the User

Stop the current tool and ask before proceeding if:
- `EDGAR_USER_AGENT` or `GOOGLE_CUSTOM_SEARCH_API_KEY` are missing from `.env`
- `credentials.json` is not in the project root
- The Google Sheet returns a permission error
- A tool that makes paid API calls is about to be re-run (check if data already exists)
- Any tool crashes with an unexpected error not covered by its documented quirks

---

## Google Sheet Column Reference

| Col | Header | Notes |
|-----|--------|-------|
| A | Company Name | |
| B | Ticker | Primary dedup key |
| C | Exchange | NYSE, TSX, ASX, LSE, TSX.V, OTC |
| D | CEO Name | |
| E | General Counsel Name | |
| F | GC Title | Exact title as found in source |
| G | GC Email | Best found email |
| H | Email Confidence | high / unverified_guess / not_found |
| I | LinkedIn Search URL | Open for manual lookup |
| J | Jurisdictions | Countries/states of operation |
| K | Total Revenue (USD) | Raw number, no $ symbol |
| L | Revenue Year | 4-digit year |
| M | Tons Ore Processed | Text + units as found |
| N | Major Projects | Semicolon-separated |
| O | Project Countries | Semicolon-separated, aligned with N |
| P | Market Cap (USD) | Raw number |
| Q | Company Website | |
| R | CIK (EDGAR) | 10-digit or null for non-US |
| S | Data Sources | EDGAR, yfinance, website |
| T | Last Updated | ISO 8601 |
| U | Notes / Flags | gc_search_needed, website_unreachable, etc. |
