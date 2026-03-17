# Mining News Digest — Workflow SOP

## Objective

Fetch mining news from 5 top industry publications, summarize the past 7 days into a concise digest using GPT-4o, and email it to `mininglegalresearch@gmail.com`.

**Quick run (after setup):**
```bash
python "Mining News Scrapper/tools/run_news_pipeline.py"
```

---

## One-Time Setup

### 1. Install dependencies
```bash
pip install -r "Mining News Scrapper/requirements.txt"
```

### 2. Configure Gmail App Password

> The pipeline sends email via Gmail SMTP. A regular password will NOT work — you need an App Password.

1. Go to **myaccount.google.com/security**
2. Enable **2-Step Verification** (required)
3. Go to **myaccount.google.com/apppasswords**
4. Create a new app password — name it `Mining News Digest`
5. Copy the 16-character password (format: `xxxx xxxx xxxx xxxx`)

### 3. Add keys to `.env` (root level)

Open `/Users/tomvillalon/Desktop/Claude Mining List Test/.env` and append:

```
# --- Mining News Digest ---
GMAIL_ADDRESS=mininglegalresearch@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
NEWS_RECIPIENT_EMAIL=mininglegalresearch@gmail.com
```

> `OPENAI_API_KEY` is already present from the AudreyBook project — no changes needed.

---

## Pipeline Steps

### Phase 1 — Fetch Articles (`fetch_mining_news.py`)

**Run:** `python "Mining News Scrapper/tools/fetch_mining_news.py"`
**Output:** `.tmp/news_articles.json`

Fetches articles published in the past 7 days from 5 publications via RSS feeds. Falls back to HTML scraping if RSS fails.

**Publications:**

| Publication | RSS Feed | Paywall |
|-------------|----------|---------|
| Mining.com | `https://www.mining.com/feed/` | No — full text |
| The Northern Miner | `https://www.northernminer.com/feed/` | Yes — headlines only |
| Kitco News | `https://www.kitco.com/rss/news.rss` | No — snippets |
| Mining Weekly | `https://www.miningweekly.com/rss` | Soft — RSS full text |
| Proactive Investors | `https://www.proactiveinvestors.com/rss/news.rss` | No — snippets |

**Rate limits / politeness:**
- 2-second sleep between each source
- User-Agent header identifies as research bot
- Respects robots.txt on HTML fallback paths only

**After running, verify:**
- `news_articles.json` exists and has 20+ articles
- All 5 sources are represented (or logged as failed with a warning)
- Northern Miner entries have short snippets (expected — paywall)

---

### Phase 2 — Summarize (`summarize_news.py`)

**Run:** `python "Mining News Scrapper/tools/summarize_news.py"`
**Output:** `.tmp/news_summary.json`

Sends all articles to GPT-4o with a structured prompt. Produces:
- **Executive Summary**: 1-2 paragraphs (150-250 words) of the top 3-5 developments
- **Source Breakdown**: 2-3 bullet points per publication

**API costs:**
- ~40 articles × ~150 tokens each = ~6,000 input tokens
- ~800 tokens output
- Estimated cost: ~$0.02-0.05 per run (GPT-4o pricing)
- Check usage at: platform.openai.com/usage

**After running, verify:**
- `news_summary.json` has `executive_summary` with 150+ words
- `source_sections` contains 5 entries, one per publication
- Each section has 2-3 non-empty bullets

---

### Phase 3 — Send Email (`send_email_digest.py`)

**Run:** `python "Mining News Scrapper/tools/send_email_digest.py"`
**Dry run:** `python "Mining News Scrapper/tools/send_email_digest.py" --dry-run`

Builds a formatted HTML email and sends it via Gmail SMTP.

Email subject: `Mining News Digest — Week of [date]`
Recipient: `NEWS_RECIPIENT_EMAIL` from `.env`

**Always do a dry run first** on initial setup:
```bash
python "Mining News Scrapper/tools/send_email_digest.py" --dry-run
```
Then open `.tmp/email_preview.html` in a browser to review the layout.

**Rate limits:**
- Gmail free accounts: 500 emails/day (well within limits for a weekly digest)
- No rate limiting needed for single sends

---

## Full Pipeline (Orchestrator)

```bash
# Standard weekly run
python "Mining News Scrapper/tools/run_news_pipeline.py"

# Preview email without sending
python "Mining News Scrapper/tools/run_news_pipeline.py" --dry-run

# Re-run GPT-4o + email only (reuse yesterday's fetch)
python "Mining News Scrapper/tools/run_news_pipeline.py" --skip-fetch
```

---

## Weekly Automation (Optional)

To run every Monday at 8 AM, add to crontab (`crontab -e`):
```
0 8 * * 1 cd "/Users/tomvillalon/Desktop/Claude Mining List Test" && python "Mining News Scrapper/tools/run_news_pipeline.py" >> /tmp/mining_news_cron.log 2>&1
```

Check cron logs: `cat /tmp/mining_news_cron.log`

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `SMTPAuthenticationError` | Wrong app password or 2FA not enabled | Re-generate app password at myaccount.google.com/apppasswords |
| `OPENAI_API_KEY not set` | Missing .env key | Add `OPENAI_API_KEY=sk-...` to root `.env` |
| `0 articles total` | All RSS feeds down | Wait and retry; check feed URLs manually in browser |
| `feedparser bozo=True` | Malformed RSS XML | Script auto-tries fallback URL; if both fail, source is skipped |
| `SSL certificate error` | Older publication site | Script auto-retries with `verify=False` and logs a warning |
| `RateLimitError` from OpenAI | Too many API calls | Script auto-waits 60s and retries once |
| `ModuleNotFoundError` | Dependencies not installed | Run `pip install -r "Mining News Scrapper/requirements.txt"` |
| Northern Miner has very short snippets | Paywall (expected) | Normal behavior — GPT-4o summarizes the headline only |
| Email arrives in spam | Sender reputation | Mark as "Not spam" and add sender to contacts |

---

## Intermediate Files (`.tmp/`)

| File | Created by | Contents |
|------|-----------|----------|
| `news_articles.json` | `fetch_mining_news.py` | Array of article objects with source, title, url, published_date, snippet, paywall |
| `news_summary.json` | `summarize_news.py` | Structured digest: week_of, article_count, executive_summary, source_sections, raw_digest_markdown |
| `email_preview.html` | `send_email_digest.py --dry-run` | Full HTML email body for browser preview |

All `.tmp/` files are disposable — safe to delete and regenerate.

---

## Data Sources Reference

These RSS feeds are checked each run. If a feed URL changes, update the `SOURCES` list in [fetch_mining_news.py](../tools/fetch_mining_news.py).

- **Mining.com**: https://www.mining.com/feed/
- **The Northern Miner**: https://www.northernminer.com/feed/
- **Kitco News**: https://www.kitco.com/rss/news.rss (fallback: https://www.kitco.com/rss/KitcoNews.rss)
- **Mining Weekly**: https://www.miningweekly.com/rss (fallback: https://www.miningweekly.com/rss/articles)
- **Proactive Investors**: https://www.proactiveinvestors.com/rss/news.rss (fallback: .co.uk domain)
