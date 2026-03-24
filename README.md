# Palo Alto Motivated Seller Lead System

Automatically finds pre-market real estate leads in Palo Alto, CA every Sunday evening and emails you a formatted report with contact details and call scripts.

---

## What It Does

Scrapes three free Santa Clara County public record sources weekly:

| Source | Lead type | What it means |
|--------|-----------|---------------|
| **County Recorder** | Pre-foreclosure (NOD) | Owner is 90+ days behind on mortgage |
| **Superior Court** | Probate / Estate | Owner died, heirs need to liquidate |
| **Tax Collector** | Tax delinquent | Owner hasn't paid property taxes for years |

- Filters all results for **Palo Alto zip codes** (94301–94306)
- Enriches each lead with **Assessor data** (owner name, mailing address, assessed value)
- **Deduplicates** across weeks — you only see new leads each Monday
- Sends a **rich HTML email** Sunday evening with contact info and call scripts built in

---

## Setup (One Time)

### 1. Install Python dependencies

```bash
cd "/Users/benjaminying/Documents/Claude Code/Palo Alto Real Esate"
pip3 install -r requirements.txt
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` and fill in:

```
EMAIL_SENDER=yourgmail@gmail.com
EMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
EMAIL_RECIPIENT=yourgmail@gmail.com
```

**Getting a Gmail App Password:**
1. Go to https://myaccount.google.com/security
2. Enable 2-Step Verification (if not already)
3. Go to https://myaccount.google.com/apppasswords
4. Create a new App Password → select "Mail" → copy the 16-character code

### 3. Test your setup

This sends a sample report with fake leads to verify email works:

```bash
python3 main.py --test
```

Check your inbox. If you see the email, everything is working.

### 4. Install the macOS scheduler

This installs a Launch Agent that runs automatically every Sunday at 6:00 PM — even if the terminal is closed. Your Mac just needs to be awake.

```bash
bash setup_scheduler.sh
```

---

## Daily Usage

**Monday morning:** Check your inbox for the weekly report email.

Each lead shows:
- Property address
- Owner / decedent name
- Contact person (executor, attorney, or owner) with phone/email
- Lead type and why they're motivated
- Assessed property value
- "Search for phone" link for leads that need skip tracing

---

## Manual Commands

| Command | What it does |
|---------|-------------|
| `python3 main.py` | Run immediately (scrape + email right now) |
| `python3 main.py --test` | Send a sample report to test email setup |
| `python3 main.py --import-csv leads.csv --type probate` | Add leads from a manual CSV export |

### Manual CSV import

If a scraper fails (government websites change), you can download data manually from the county site and import it:

```bash
python3 main.py --import-csv my_leads.csv --type foreclosure
```

CSV column names accepted (case-insensitive):
`address`, `owner_name`, `contact_name`, `contact_phone`, `contact_email`, `contact_role`, `filing_date`, `doc_number`, `case_number`, `amount_owed`, `extra_info`

---

## Data Sources (Free, Public)

| Site | What to search manually if scraper fails |
|------|------------------------------------------|
| **Santa Clara County Recorder** | https://ccr.sccgov.org/ → Document type: ND (Notice of Default) or NTS |
| **Santa Clara County Courts** | https://www.scscourt.org/ → Case type: Probate (PR) |
| **Tax Collector** | https://www.sccgov.org/sites/tax/Pages/Tax-Defaulted-Property.aspx |
| **Assessor lookup** | https://eaas.sccgov.org/ → Search by address or APN |

---

## Sales Scripts

Full call scripts are in `sales_scripts/`:

- `probate_script.md` — calling executors and estate attorneys
- `foreclosure_script.md` — calling pre-foreclosure homeowners
- `divorce_script.md` — calling family law attorneys and parties

Quick-reference versions of all scripts are included at the bottom of every email report.

---

## Lead History

All leads are stored in `data/leads.db` (SQLite). To view:

```bash
sqlite3 data/leads.db "SELECT lead_type, address, owner_name, contact_phone, first_seen FROM leads ORDER BY first_seen DESC LIMIT 20;"
```

---

## Troubleshooting

**Scrapers return 0 results:**
Government websites occasionally change their HTML structure. Check the log at `data/run.log`. Use `--import-csv` to manually add leads from the county site while the scraper is updated.

**Email not sending:**
Make sure you're using a **Gmail App Password**, not your regular password. Regular passwords don't work with SMTP.

**Mac was asleep on Sunday:**
The Launch Agent will run when your Mac next wakes up. Or run manually: `python3 main.py`

**Check scheduler status:**
```bash
launchctl list | grep paloaltoleads
```

**Uninstall the scheduler:**
```bash
launchctl unload ~/Library/LaunchAgents/com.paloaltoleads.weekly.plist
rm ~/Library/LaunchAgents/com.paloaltoleads.weekly.plist
```

---

## File Structure

```
├── main.py                    # Entry point
├── config.py                  # Settings (URLs, paths, email config)
├── database.py                # SQLite deduplication
├── scrapers/
│   ├── recorder.py            # County Recorder — NOD/pre-foreclosure
│   ├── probate.py             # Superior Court — probate cases
│   └── tax_default.py         # Tax Collector — delinquent properties
├── enrichment/
│   └── assessor.py            # Assessor lookup for owner/value data
├── report/
│   ├── generator.py           # HTML report builder
│   └── emailer.py             # Gmail SMTP sender
├── templates/
│   └── report.html            # Email template (Jinja2)
├── sales_scripts/
│   ├── probate_script.md
│   ├── foreclosure_script.md
│   └── divorce_script.md
├── data/
│   ├── leads.db               # Lead history database
│   ├── run.log                # Run logs
│   └── reports/               # Saved weekly HTML reports
└── setup_scheduler.sh         # macOS Launch Agent installer
```
