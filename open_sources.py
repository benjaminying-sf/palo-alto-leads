#!/usr/bin/env python3
"""
Open all manual data sources in your browser at once.

Run this Monday morning:
  python open_sources.py

It will open 3 tabs — one for each data source. Check each one for Palo Alto
leads from the past week, then use --import-csv to add them to your database.
"""
import subprocess
import sys

SOURCES = [
    (
        "Probate — Santa Clara Superior Court",
        "https://portal.scscourt.org/search",
        "Search: Case Type = PR (Probate), last 7 days",
    ),
    (
        "Pre-Foreclosure — Santa Clara Recorder",
        "https://clerkrecorder.santaclaracounty.gov/official-records/records-search",
        "Search: Document Type = ND (Notice of Default), last 7 days",
    ),
    (
        "Tax Default — DTAC Auction List",
        "https://dtac.santaclaracounty.gov/taxes/public-auction-tax-defaulted-properties",
        "Download the property list if available; look for Palo Alto addresses",
    ),
]


def main():
    print("\nOpening manual data sources in your browser...\n")
    for i, (name, url, instructions) in enumerate(SOURCES, 1):
        print(f"  {i}. {name}")
        print(f"     {instructions}")
        print(f"     {url}\n")
        # Open in default browser (Safari on macOS by default)
        subprocess.run(["open", url])

    print("=" * 60)
    print("After checking each site:")
    print()
    print("  Save any leads as CSV, then run:")
    print("    python main.py --import-csv FILE.csv --type probate")
    print("    python main.py --import-csv FILE.csv --type foreclosure")
    print("    python main.py --import-csv FILE.csv --type tax_default")
    print()
    print("Expected CSV columns (any subset works):")
    print("  address, owner_name, contact_name, contact_phone,")
    print("  contact_email, filing_date, case_number, extra_info")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
