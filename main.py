#!/usr/bin/env python3
"""
Palo Alto Motivated Seller Lead System
=======================================
Runs every Sunday evening, scrapes Santa Clara County public records for
motivated seller leads (probate, pre-foreclosure, tax delinquent, divorce),
deduplicates against prior weeks, and emails a formatted HTML report.

Usage:
  python main.py                    # Run immediately (for testing)
  python main.py --schedule         # Start the weekly scheduler (Sunday 6pm)
  python main.py --test             # Generate sample report (no scraping)
  python main.py --import-csv FILE --type TYPE   # Manually add leads from CSV

Lead types for --import-csv: probate | foreclosure | tax_default | divorce
"""

import argparse
import csv
import logging
import os
import sys
from datetime import datetime, timedelta

import schedule
import time

import config
import database
from enrichment import assessor
from report import generator, emailer
from scrapers.recorder import RecorderScraper
from scrapers.probate import ProbateScraper
from scrapers.obituary import ObituaryScraper
from scrapers.tax_default import TaxDefaultScraper
from scrapers.bankruptcy import BankruptcyScraper

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(config.BASE_DIR, "data", "run.log"), mode="a"),
    ],
)
logger = logging.getLogger("main")


# ── Core workflow ──────────────────────────────────────────────────────────────

def run_weekly(days_back: int = 7):
    """Full end-to-end pipeline: scrape → enrich → deduplicate → report → email."""
    logger.info("=" * 60)
    logger.info("LEAD RUN — %s (looking back %d days)", datetime.now().strftime("%Y-%m-%d %H:%M"), days_back)
    logger.info("=" * 60)

    database.init_db()

    all_leads = []

    # ── 1. Collect leads from all sources ─────────────────────────────────────
    logger.info("Step 1/4 — Collecting leads from public records...")

    scrapers = [
        ("Recorder (NODs)", RecorderScraper()),
        ("Obituaries (Google News)", ObituaryScraper()),   # Palo Alto-specific death leads
        ("Probate Court", ProbateScraper()),               # Backup: county-wide with verification links
        ("Tax Collector", TaxDefaultScraper()),
        ("Bankruptcy Court (CourtListener)", BankruptcyScraper()),
    ]

    for name, scraper in scrapers:
        try:
            logger.info("  Running %s scraper...", name)
            leads = scraper.run(days_back=days_back)
            all_leads.extend(leads)
            logger.info("  %s: %d leads found", name, len(leads))
        except Exception as exc:
            logger.error("  %s failed: %s", name, exc, exc_info=True)

    logger.info("Total raw leads collected: %d", len(all_leads))

    # ── 2. Enrich with Assessor data ──────────────────────────────────────────
    logger.info("Step 2/4 — Enriching with Assessor property data...")
    enriched = []
    for lead in all_leads:
        try:
            enriched.append(assessor.enrich_lead(lead))
        except Exception as exc:
            logger.debug("Assessor enrichment failed for %s: %s", lead.get("address"), exc)
            enriched.append(lead)
    all_leads = enriched

    # ── 3. Deduplicate (save new leads to database) ────────────────────────────
    logger.info("Step 3/4 — Deduplicating against history...")
    new_leads = []
    for lead in all_leads:
        is_new = database.upsert_lead(lead)
        if is_new:
            new_leads.append(lead)

    logger.info("New leads (not seen before): %d of %d", len(new_leads), len(all_leads))

    # ── 4. Generate report & email ─────────────────────────────────────────────
    logger.info("Step 4/4 — Generating report and sending email...")

    if not new_leads:
        logger.info("No new leads this week — sending a brief 'no new leads' notification.")
        # Still send an email so you know the system ran
        html = _no_leads_html()
    else:
        html = generator.generate_report(new_leads)

    email_sent = emailer.send_report(html, len(new_leads))
    database.log_run(
        new_leads=len(new_leads),
        total_leads=len(all_leads),
        email_sent=email_sent,
    )

    logger.info("Run complete. %d new leads emailed.", len(new_leads))
    logger.info("=" * 60)


# ── Manual CSV import ──────────────────────────────────────────────────────────

def import_csv(filepath: str, lead_type: str):
    """
    Import leads from a manually downloaded CSV.

    Expected columns (case-insensitive):
      address, owner_name, contact_name, contact_phone, contact_email,
      contact_role, filing_date, doc_number, case_number, amount_owed, extra_info

    Useful when a scraper fails and you pull data manually from the county website.
    """
    database.init_db()
    valid_types = [
        config.LEAD_TYPE_PROBATE,
        config.LEAD_TYPE_FORECLOSURE,
        config.LEAD_TYPE_TAX_DEFAULT,
        config.LEAD_TYPE_DIVORCE,
    ]
    if lead_type not in valid_types:
        print(f"ERROR: Invalid type '{lead_type}'. Choose from: {', '.join(valid_types)}")
        sys.exit(1)

    imported = 0
    skipped = 0

    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Normalize headers to lowercase
        for row in reader:
            normed = {k.strip().lower(): v.strip() for k, v in row.items()}
            lead = {
                "lead_type": lead_type,
                "address": normed.get("address", ""),
                "owner_name": normed.get("owner_name", "") or normed.get("owner", ""),
                "contact_name": normed.get("contact_name", ""),
                "contact_phone": normed.get("contact_phone", "") or normed.get("phone", ""),
                "contact_email": normed.get("contact_email", "") or normed.get("email", ""),
                "contact_role": normed.get("contact_role", ""),
                "filing_date": normed.get("filing_date", "") or normed.get("date", ""),
                "doc_number": normed.get("doc_number", "") or normed.get("document_number", ""),
                "case_number": normed.get("case_number", ""),
                "amount_owed": normed.get("amount_owed", "") or normed.get("amount", ""),
                "extra_info": normed.get("extra_info", "") or normed.get("notes", ""),
            }

            # Enrich with Assessor data
            lead = assessor.enrich_lead(lead)

            is_new = database.upsert_lead(lead)
            if is_new:
                imported += 1
            else:
                skipped += 1

    print(f"Import complete: {imported} new leads added, {skipped} duplicates skipped.")

    # Generate and email a report with only the newly imported leads
    if imported > 0:
        with database.get_connection() as conn:
            since = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
            rows = conn.execute(
                "SELECT * FROM leads WHERE first_seen >= ?", (since,)
            ).fetchall()
        new_leads = [dict(r) for r in rows]
        html = generator.generate_report(new_leads, report_date=f"Manual Import — {datetime.now().strftime('%B %d, %Y')}")
        emailer.send_report(html, imported)


# ── Test mode ─────────────────────────────────────────────────────────────────

def run_test():
    """Generate a sample report with fake data to verify email + template setup."""
    logger.info("Running in TEST MODE — no real scraping, sending sample report...")
    database.init_db()

    sample_leads = [
        {
            "lead_type": config.LEAD_TYPE_PROBATE,
            "address": "123 Emerson St, Palo Alto, CA 94301",
            "owner_name": "Estate of Jane Doe",
            "contact_name": "Robert Smith (Executor)",
            "contact_phone": "(650) 555-0101",
            "contact_email": "rsmith@examplelaw.com",
            "contact_role": "Attorney for Estate",
            "filing_date": datetime.now().strftime("%m/%d/%Y"),
            "case_number": "23PR-000001",
            "assessed_value": "$1,450,000",
            "extra_info": "SAMPLE DATA — Probate case. Estate has 3 heirs. Attorney says they want to close by end of quarter.",
            "google_search_url": "https://www.google.com",
        },
        {
            "lead_type": config.LEAD_TYPE_FORECLOSURE,
            "address": "456 University Ave, Palo Alto, CA 94301",
            "owner_name": "Michael Johnson",
            "contact_name": "Pacific Trustee Services",
            "contact_phone": "(800) 555-0202",
            "contact_email": "",
            "contact_role": "Trustee (NOD filer)",
            "filing_date": datetime.now().strftime("%m/%d/%Y"),
            "doc_number": "24-001234",
            "assessed_value": "$2,100,000",
            "amount_owed": "$380,000",
            "extra_info": "SAMPLE DATA — Notice of Default filed. Owner is 6 months behind.",
            "google_search_url": "https://www.google.com",
        },
        {
            "lead_type": config.LEAD_TYPE_TAX_DEFAULT,
            "address": "789 Ramona St, Palo Alto, CA 94303",
            "owner_name": "Williams Family Trust",
            "contact_name": "Williams Family Trust",
            "contact_phone": "",
            "contact_email": "",
            "contact_role": "Property Owner (skip trace for phone)",
            "filing_date": "2019",
            "amount_owed": "$48,200",
            "assessed_value": "$890,000",
            "extra_info": "SAMPLE DATA — Tax defaulted since 2019 (5 years). Significant risk of county sale.",
            "google_search_url": "https://www.google.com",
        },
    ]

    html = generator.generate_report(sample_leads, report_date="TEST — " + datetime.now().strftime("%B %d, %Y"))
    email_sent = emailer.send_report(html, len(sample_leads))

    if email_sent:
        print(f"\nTest report sent to {config.EMAIL_RECIPIENT}")
    else:
        print("\nEmail send failed — check your .env credentials.")
        print(f"Report saved to: {config.REPORTS_DIR}")


# ── Utilities ─────────────────────────────────────────────────────────────────

def _no_leads_html() -> str:
    return f"""
    <html><body style="font-family:sans-serif;padding:24px;color:#333;">
    <h2>Palo Alto Lead Report — {datetime.now().strftime('%B %d, %Y')}</h2>
    <p>No new leads found this week. All public records checked were either previously
    captured or returned no new Palo Alto results.</p>
    <p>The system ran successfully at {datetime.now().strftime('%H:%M')}.</p>
    </body></html>
    """


# ── Scheduler ─────────────────────────────────────────────────────────────────

def start_scheduler():
    logger.info(
        "Scheduler started. Will run every %s at %02d:%02d.",
        config.REPORT_DAY.capitalize(),
        config.REPORT_HOUR,
        config.REPORT_MINUTE,
    )

    run_time = f"{config.REPORT_HOUR:02d}:{config.REPORT_MINUTE:02d}"
    getattr(schedule.every(), config.REPORT_DAY).at(run_time).do(run_weekly)

    print(f"\nScheduler running. Next report: {config.REPORT_DAY.capitalize()} at {run_time}.")
    print("Leave this terminal open, or set up the Launch Agent (see README) to run it as a background service.\n")
    print("Press Ctrl+C to stop.\n")

    while True:
        schedule.run_pending()
        time.sleep(60)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Palo Alto Motivated Seller Lead System"
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Start the weekly scheduler (runs every Sunday at 6pm by default)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Send a sample report with fake data to verify setup",
    )
    parser.add_argument(
        "--import-csv",
        metavar="FILE",
        help="Import leads from a CSV file",
    )
    parser.add_argument(
        "--type",
        choices=[
            config.LEAD_TYPE_PROBATE,
            config.LEAD_TYPE_FORECLOSURE,
            config.LEAD_TYPE_TAX_DEFAULT,
            config.LEAD_TYPE_DIVORCE,
        ],
        help="Lead type for --import-csv",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=7,
        metavar="N",
        help="How many days back to search (default: 7). Use 365 for a 12-month backfill.",
    )

    args = parser.parse_args()

    if args.test:
        run_test()
    elif args.import_csv:
        if not args.type:
            print("ERROR: --import-csv requires --type. Example: --type probate")
            sys.exit(1)
        import_csv(args.import_csv, args.type)
    elif args.schedule:
        start_scheduler()
    else:
        run_weekly(days_back=args.days_back)


if __name__ == "__main__":
    main()
