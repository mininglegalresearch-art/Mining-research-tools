"""
tools/send_email_digest.py

Builds a formatted HTML email from the GPT-4o digest and sends it via Gmail SMTP.

Input:   .tmp/news_summary.json
Output:  Email sent to NEWS_RECIPIENT_EMAIL (or .tmp/email_preview.html in --dry-run mode)

Required .env keys:
  GMAIL_ADDRESS        — sender Gmail address
  GMAIL_APP_PASSWORD   — 16-char Gmail app password (2FA must be enabled)
  NEWS_RECIPIENT_EMAIL — recipient address

Setup (one-time):
  1. Enable 2-Step Verification at myaccount.google.com/security
  2. Create an App Password: myaccount.google.com/apppasswords
     Name it "Mining News Digest" — copy the 16-char password
  3. Add to .env:  GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_DIR = Path(__file__).parent.parent
TMP_DIR = PROJECT_DIR / ".tmp"
INPUT_FILE    = TMP_DIR / "news_summary.json"
OUTREACH_FILE = TMP_DIR / "outreach_targets.json"
def next_preview_file():
    """Return the next versioned preview path: digest_preview_v1.html, v2, v3..."""
    v = 1
    while (TMP_DIR / f"digest_preview_v{v}.html").exists():
        v += 1
    return TMP_DIR / f"digest_preview_v{v}.html"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587   # STARTTLS


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Mining News Digest</title>
  <style>
    body {{
      font-family: Arial, Helvetica, sans-serif;
      max-width: 680px;
      margin: 0 auto;
      color: #222;
      line-height: 1.6;
      background: #f4f4f4;
    }}
    .wrapper {{
      background: #ffffff;
      border-radius: 4px;
      overflow: hidden;
    }}
    .header {{
      background: #1a1a2e;
      color: #ffffff;
      padding: 24px 32px;
    }}
    .header h1 {{
      margin: 0 0 4px;
      font-size: 20px;
      font-weight: 700;
      letter-spacing: 0.3px;
    }}
    .header .meta {{
      margin: 0;
      font-size: 13px;
      color: #9999bb;
    }}
    .exec-summary {{
      background: #f8f9fa;
      border-left: 4px solid #c8a951;
      padding: 20px 28px 20px 24px;
      margin: 0;
    }}
    .exec-summary h2 {{
      margin: 0 0 10px;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      color: #555;
    }}
    .exec-summary p {{
      margin: 0 0 10px;
      font-size: 14px;
      color: #333;
    }}
    .exec-summary p:last-child {{
      margin-bottom: 0;
    }}
    .breakdown {{
      padding: 20px 32px 8px;
    }}
    .breakdown h2 {{
      margin: 0 0 16px;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      color: #555;
      border-bottom: 1px solid #eee;
      padding-bottom: 8px;
    }}
    .source-block {{
      margin-bottom: 20px;
    }}
    .source-name {{
      font-size: 14px;
      font-weight: 700;
      color: #1a1a2e;
      margin: 0 0 6px;
    }}
    ul {{
      margin: 0;
      padding-left: 18px;
    }}
    li {{
      margin-bottom: 5px;
      font-size: 13px;
      color: #444;
    }}
    .no-articles {{
      font-size: 13px;
      color: #999;
      font-style: italic;
    }}
    .outreach {{
      padding: 20px 32px 8px;
      border-top: 3px solid #1a1a2e;
    }}
    .outreach h2 {{
      margin: 0 0 4px;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      color: #1a1a2e;
    }}
    .outreach .subtitle {{
      font-size: 12px;
      color: #888;
      margin: 0 0 16px;
      font-style: italic;
    }}
    .target-card {{
      background: #f8f9fa;
      border-left: 4px solid #8b1a1a;
      padding: 14px 16px;
      margin-bottom: 14px;
      border-radius: 0 4px 4px 0;
    }}
    .target-header {{
      display: flex;
      justify-content: space-between;
      margin-bottom: 6px;
    }}
    .target-company {{
      font-size: 14px;
      font-weight: 700;
      color: #1a1a2e;
    }}
    .target-badge {{
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      padding: 2px 7px;
      border-radius: 3px;
      color: #fff;
    }}
    .badge-high   {{ background: #8b1a1a; }}
    .badge-medium {{ background: #b8720a; }}
    .badge-low    {{ background: #555; }}
    .target-meta {{
      font-size: 12px;
      color: #666;
      margin-bottom: 8px;
    }}
    .target-situation {{
      font-size: 13px;
      color: #333;
      margin-bottom: 6px;
    }}
    .target-rationale {{
      font-size: 13px;
      color: #444;
      font-style: italic;
      margin-bottom: 8px;
    }}
    .target-contacts {{
      font-size: 12px;
      color: #555;
      border-top: 1px solid #ddd;
      padding-top: 7px;
      margin-top: 4px;
    }}
    .target-contacts strong {{
      color: #333;
    }}
    .no-targets {{
      font-size: 13px;
      color: #999;
      font-style: italic;
      padding: 4px 0 12px;
    }}
    .footer {{
      padding: 12px 32px;
      background: #f8f9fa;
      border-top: 1px solid #eee;
      font-size: 11px;
      color: #aaa;
    }}
    a {{ color: #0066cc; }}
  </style>
</head>
<body>
<div class="wrapper">

  <!-- HEADER -->
  <div class="header">
    <h1>Mining News Digest</h1>
    <p class="meta">Week of {week_of}&nbsp;&nbsp;·&nbsp;&nbsp;{article_count} articles&nbsp;&nbsp;·&nbsp;&nbsp;{source_count} publications</p>
  </div>

  <!-- EXECUTIVE SUMMARY -->
  <div class="exec-summary">
    <h2>Executive Summary</h2>
    {exec_paragraphs}
  </div>

  <!-- OUTREACH OPPORTUNITIES -->
  {outreach_section}

  <!-- SOURCE BREAKDOWN -->
  <div class="breakdown">
    <h2>Source Breakdown</h2>
    {source_blocks}
  </div>

  <!-- FOOTER -->
  <div class="footer">
    Generated {generated_date}&nbsp;&nbsp;·&nbsp;&nbsp;Powered by GPT-4o&nbsp;&nbsp;·&nbsp;&nbsp;
    Sources: Mining.com, The Northern Miner, Mining Journal, Mining Magazine, Mining Weekly
  </div>

</div>
</body>
</html>
"""


DISPUTE_LABELS = {
    "permit_revocation":  "Permit Revocation",
    "expropriation":      "Expropriation",
    "enforcement_action": "Enforcement Action",
    "treaty_concern":     "Treaty Concern",
    "contract_dispute":   "Contract Dispute",
    "force_majeure":      "Force Majeure",
    "environmental":      "Environmental",
    "community_rights":   "Community Rights",
    "jv_dispute":         "JV Dispute",
    "political_risk":     "Political Risk",
    "other":              "Dispute Signal",
}


def build_outreach_html(targets):
    """Build the Outreach Opportunities HTML section."""
    if not targets:
        return (
            '<div class="outreach">'
            '<h2>Outreach Opportunities</h2>'
            '<p class="subtitle">International Arbitration Early Engagement</p>'
            '<p class="no-targets">No significant dispute signals identified in this week\'s news.</p>'
            '</div>'
        )

    cards = ""
    for t in targets:
        company   = t.get("company_name", "Unknown Company")
        ticker    = t.get("ticker")
        juris     = t.get("jurisdiction", "")
        d_type    = t.get("dispute_type", "other")
        situation = t.get("situation_summary", "")
        rationale = t.get("engagement_rationale", "")
        urgency   = t.get("urgency", "medium").lower()
        headline  = t.get("source_headline", "")
        contact_lines = t.get("contact_summary", [])

        badge_class = f"badge-{urgency}" if urgency in ("high", "medium", "low") else "badge-medium"
        label = DISPUTE_LABELS.get(d_type, "Dispute Signal")
        meta_parts = []
        if juris: meta_parts.append(juris)
        if ticker: meta_parts.append(ticker)
        meta_str = " &nbsp;·&nbsp; ".join(meta_parts)

        contacts_html = ""
        if contact_lines:
            items = "".join(f"<div>{c}</div>" for c in contact_lines)
            contacts_html = f'<div class="target-contacts"><strong>Contact:</strong><br>{items}</div>'

        headline_html = ""
        if headline:
            headline_html = f'<div style="font-size:11px;color:#999;margin-bottom:6px;">Source: {headline}</div>'

        cards += f"""
    <div class="target-card">
      <div class="target-header">
        <span class="target-company">{company}</span>
        <span class="target-badge {badge_class}">{urgency.upper()} · {label}</span>
      </div>
      {"<div class='target-meta'>" + meta_str + "</div>" if meta_str else ""}
      {headline_html}
      <div class="target-situation">{situation}</div>
      <div class="target-rationale">{rationale}</div>
      {contacts_html}
    </div>"""

    return (
        '<div class="outreach">'
        '<h2>Outreach Opportunities</h2>'
        '<p class="subtitle">International Arbitration Early Engagement — identified from this week\'s news</p>'
        + cards +
        '</div>'
    )


def build_html(summary, targets=None):
    """Render the HTML email body from the summary dict."""
    # Executive summary — split into paragraphs
    exec_text = summary.get("executive_summary", "No summary available.")
    paragraphs = [p.strip() for p in exec_text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [exec_text]
    exec_html = "\n    ".join(f"<p>{p}</p>" for p in paragraphs)

    # Source sections
    source_blocks_html = ""
    for section in summary.get("source_sections", []):
        bullets = section.get("bullets", [])
        source_name = section.get("source", "Unknown")

        if not bullets or bullets == ["No articles this week."]:
            inner = '<p class="no-articles">No articles this week.</p>'
        else:
            items = "\n        ".join(f"<li>{b}</li>" for b in bullets)
            inner = f"<ul>\n        {items}\n      </ul>"

        source_blocks_html += f"""
    <div class="source-block">
      <div class="source-name">{source_name}</div>
      {inner}
    </div>"""

    week_of = summary.get("week_of", date.today().isoformat())
    # Format date nicely: "2026-03-16" → "March 16, 2026"
    try:
        d = date.fromisoformat(week_of)
        week_formatted = d.strftime("%B %-d, %Y")
    except Exception:
        week_formatted = week_of

    outreach_html = build_outreach_html(targets or [])

    return HTML_TEMPLATE.format(
        week_of=week_formatted,
        article_count=summary.get("article_count", 0),
        source_count=len(summary.get("sources_covered", [])),
        exec_paragraphs=exec_html,
        outreach_section=outreach_html,
        source_blocks=source_blocks_html,
        generated_date=date.today().strftime("%B %-d, %Y"),
    )


def build_plain_text(summary, targets=None):
    """Build a plain-text fallback version of the digest."""
    lines = []
    week_of = summary.get("week_of", date.today().isoformat())
    lines.append(f"Mining News Digest — Week of {week_of}")
    lines.append("=" * 50)
    lines.append("")
    lines.append("EXECUTIVE SUMMARY")
    lines.append("-" * 20)
    lines.append(summary.get("executive_summary", "No summary available."))
    lines.append("")

    if targets:
        lines.append("OUTREACH OPPORTUNITIES")
        lines.append("-" * 20)
        lines.append("International Arbitration Early Engagement")
        lines.append("")
        for t in targets:
            lines.append(f"{t.get('company_name', 'Unknown')} [{t.get('urgency','').upper()}]")
            lines.append(f"Jurisdiction: {t.get('jurisdiction', '')}")
            lines.append(f"Situation: {t.get('situation_summary', '')}")
            lines.append(f"Why now: {t.get('engagement_rationale', '')}")
            for c in t.get("contact_summary", []):
                lines.append(f"  {c}")
            lines.append("")

    lines.append("SOURCE BREAKDOWN")
    lines.append("-" * 20)

    for section in summary.get("source_sections", []):
        lines.append(f"\n{section.get('source', 'Unknown')}:")
        for bullet in section.get("bullets", []):
            lines.append(f"  • {bullet}")

    lines.append("")
    lines.append("---")
    lines.append(f"Generated {date.today().isoformat()} | Powered by GPT-4o")
    return "\n".join(lines)


def send_email(html_body, plain_body, subject, sender, recipient, app_password):
    """Send via Gmail SMTP with STARTTLS. Raises on failure."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(sender, app_password)
        server.sendmail(sender, recipient, msg.as_string())


def main():
    parser = argparse.ArgumentParser(description="Send Mining News Digest Email")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the email but write to .tmp/email_preview.html instead of sending",
    )
    args = parser.parse_args()

    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run summarize_news.py first.")
        sys.exit(1)

    with open(INPUT_FILE) as f:
        summary = json.load(f)

    # Load outreach targets (optional — won't fail if missing)
    targets = []
    if OUTREACH_FILE.exists():
        with open(OUTREACH_FILE) as f:
            targets = json.load(f)

    print("=" * 60)
    print("  Step 4: Send Email Digest")
    print(f"  Mode: {'DRY RUN (no email sent)' if args.dry_run else 'LIVE'}")
    print(f"  Outreach targets: {len(targets)}")
    print("=" * 60)

    # Build email content
    html_body = build_html(summary, targets)
    plain_body = build_plain_text(summary, targets)

    week_of = summary.get("week_of", date.today().isoformat())
    try:
        d = date.fromisoformat(week_of)
        week_formatted = d.strftime("%B %-d, %Y")
    except Exception:
        week_formatted = week_of
    subject = f"Mining News Digest — Week of {week_formatted}"

    if args.dry_run:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        preview_file = next_preview_file()
        with open(preview_file, "w") as f:
            f.write(html_body)
        print(f"\n  [DRY RUN] Email preview written to {preview_file}")
        print(f"  Subject: {subject}")
        print("  Open the preview file in a browser to review before sending.")
        return

    # Live send — validate .env
    sender = os.getenv("GMAIL_ADDRESS")
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("NEWS_RECIPIENT_EMAIL")

    missing = [k for k, v in [
        ("GMAIL_ADDRESS", sender),
        ("GMAIL_APP_PASSWORD", app_password),
        ("NEWS_RECIPIENT_EMAIL", recipient),
    ] if not v]

    if missing:
        print(f"ERROR: Missing .env keys: {', '.join(missing)}")
        print("  See workflows/mining_news_digest.md for setup instructions.")
        sys.exit(1)

    print(f"\n  Sending to: {recipient}")
    print(f"  Subject: {subject}")

    try:
        send_email(html_body, plain_body, subject, sender, recipient, app_password)
        print(f"\n  Email sent successfully to {recipient}")
        print("  Check your inbox — delivery usually takes under 1 minute.")
    except smtplib.SMTPAuthenticationError:
        print("\nERROR: Gmail authentication failed.")
        print("  Make sure:")
        print("  1. 2-Step Verification is ON at myaccount.google.com/security")
        print("  2. GMAIL_APP_PASSWORD is a valid app password (16 chars)")
        print("  3. Setup guide: myaccount.google.com/apppasswords")
        sys.exit(1)
    except smtplib.SMTPRecipientsRefused as e:
        print(f"\nERROR: Recipient address refused: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR sending email: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
