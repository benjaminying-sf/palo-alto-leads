"""
Palo Alto Obituary scraper — finds recently deceased Palo Alto residents.

Why obituaries beat probate:
  • Probate filings lag death by months (estate must be opened first).
  • Obituaries are published within days of death — much earlier signal.
  • Results are already Palo Alto-specific, so no county-wide noise.

Data source: Google News RSS
  https://news.google.com/rss/search?q=obituary+"palo+alto"

Name-to-address lookup:
  People-search sites (TruePeopleSearch, FastPeopleSearch, WhitePages) all
  block automated requests, so we generate one-click verification links
  instead. Each lead card in the email includes:
    • Link to the original obituary article
    • Google search: "NAME" "Palo Alto" property home
    • TruePeopleSearch direct link
    • County Assessor link (if you have an address to confirm APN)
"""

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional

import requests

import config
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Google News RSS — obituaries mentioning "palo alto"
OBIT_RSS_URL = (
    "https://news.google.com/rss/search"
    "?q=obituary+%22palo+alto%22"
    "&hl=en-US&gl=US&ceid=US:en"
)

# Titles that are roundup articles, not individual obituaries
ROUNDUP_PATTERNS = re.compile(
    r"obituaries?:\s*(local|recent|this week|residents who died)",
    re.IGNORECASE,
)


class ObituaryScraper(BaseScraper):
    """
    Scrapes Google News RSS for Palo Alto obituaries.

    Returns leads with the deceased's name and one-click verification links.
    These are already Palo Alto-specific — far more targeted than the
    county-wide probate portal results.
    """

    def run(self, days_back: int = 7) -> List[dict]:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days_back)
        logger.info(
            "Scanning Google News RSS for Palo Alto obituaries since %s...",
            cutoff.strftime("%Y-%m-%d"),
        )

        items = self._fetch_rss()
        logger.info("RSS returned %d total items", len(items))

        leads = []
        for item in items:
            if not self._is_recent(item.get("pub_date", ""), cutoff):
                continue
            lead = self._to_lead(item)
            if lead:
                leads.append(lead)

        # Deduplicate by name (multiple sources may list same person)
        seen_names = set()
        unique_leads = []
        for lead in leads:
            key = lead["owner_name"].lower().strip()
            if key not in seen_names:
                seen_names.add(key)
                unique_leads.append(lead)

        logger.info("Obituary scraper: %d new Palo Alto leads this week", len(unique_leads))
        return unique_leads

    # ── RSS fetching ──────────────────────────────────────────────────────────

    def _fetch_rss(self) -> List[dict]:
        """Download and parse the Google News RSS feed."""
        try:
            resp = self.session.get(OBIT_RSS_URL, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as exc:
            logger.warning("Obituary RSS fetch failed: %s", exc)
            return []

        items = []
        for el in root.findall(".//item"):
            items.append({
                "title":    el.findtext("title", "").strip(),
                "link":     el.findtext("link", "").strip(),
                "pub_date": el.findtext("pubDate", "").strip(),
                "description": el.findtext("description", "").strip(),
            })
        return items

    # ── Date filtering ────────────────────────────────────────────────────────

    @staticmethod
    def _is_recent(pub_date_str: str, cutoff: datetime) -> bool:
        """Return True if the article was published after the cutoff."""
        if not pub_date_str:
            return True  # include if no date
        try:
            pub_dt = parsedate_to_datetime(pub_date_str)
            # Make cutoff timezone-aware if needed
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            return pub_dt >= cutoff
        except Exception:
            return True  # include on parse failure

    # ── Name extraction ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_name(title: str) -> Optional[str]:
        """
        Extract the deceased's full name from an obituary headline.

        Handles formats like:
          "Charlotte Catherine Marie Lahaye Bucholtz Obituary - Palo Alto, CA (1926-2026)"
          "John Wayne Luhtala Obituary - Palo Alto, CA (1942-2026) - The Mercury News"
          "Phil Bobel, Palo Alto's environmental champion, dies at 77"
          "In Memoriam: Jane Smith, beloved teacher"
          "Carolyn Mitchell Obituary - Palo Alto (1937-2026)"
        """
        # Skip roundup / non-individual articles
        if ROUNDUP_PATTERNS.search(title):
            return None

        # Pattern 1: "FULL NAME Obituary" — most Mercury News / Legacy titles
        m = re.match(r"^(.+?)\s+Obituary\b", title, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            # Sanity check: name should be 2–5 capitalized words, no dates/numbers
            if _looks_like_name(name):
                return name

        # Pattern 2: "FULL NAME, [description], dies/died/passed"
        m = re.match(
            r"^([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-\.]+){1,4}),",
            title,
        )
        if m:
            name = m.group(1).strip()
            if _looks_like_name(name):
                return name

        # Pattern 3: "In Memoriam: FULL NAME" or "In Memory of FULL NAME"
        m = re.search(
            r"(?:In Memoriam|In Memory of|Memorial for|Remembering):\s*"
            r"([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-\.]+){1,4})",
            title, re.IGNORECASE,
        )
        if m:
            name = m.group(1).strip()
            if _looks_like_name(name):
                return name

        return None

    # ── Lead builder ──────────────────────────────────────────────────────────

    def _to_lead(self, item: dict) -> Optional[dict]:
        title = item["title"]
        name = self._extract_name(title)
        if not name:
            return None

        # Extract birth–death years from title if present e.g. "(1938-2026)"
        birth_year, death_year = _extract_years(title)
        age_str = ""
        if birth_year and death_year:
            try:
                age_str = f" (age {int(death_year) - int(birth_year)})"
            except ValueError:
                pass

        obit_url  = item.get("link", "")
        pub_date  = item.get("pub_date", "")[:16]  # trim to date + time
        source    = _source_from_title(title)

        # Build one-click verification links
        google_url = (
            "https://www.google.com/search?q="
            + urllib.parse.quote_plus(f'"{name}" "Palo Alto" property home')
        )
        tps_name = re.sub(r"\s+", "-", name.lower())
        tps_url = f"https://www.truepeoplesearch.com/results?name={urllib.parse.quote(name)}&citystatezip=Palo+Alto%2C+CA"
        assessor_url = "https://www.sccassessor.org/apps/realpropertysearch.aspx"

        filing_date = ""
        if pub_date:
            try:
                filing_date = parsedate_to_datetime(pub_date).strftime("%m/%d/%Y")
            except Exception:
                filing_date = pub_date[:10]

        return {
            "lead_type":    config.LEAD_TYPE_PROBATE,
            "address":      "⚠️ Verify below — obituary lead",
            "city":         "Palo Alto",
            "owner_name":   name,
            "contact_name": f"Estate of {name}",
            "contact_phone": "",
            "contact_email": "",
            "contact_role": "Estate / Heirs (contact via probate attorney or family)",
            "filing_date":  filing_date,
            "case_number":  "",
            "extra_info": (
                f"Obituary{age_str} published {filing_date} via {source}. "
                "Click links below to verify Palo Alto property ownership."
            ),
            # Used by the email template for quick-action buttons
            "google_search_url": google_url,
            "assessor_url":      assessor_url,
            "obit_url":          obit_url,
            "tps_url":           tps_url,
        }


# ── Module-level helpers ───────────────────────────────────────────────────────

def _looks_like_name(text: str) -> bool:
    """
    Basic sanity check: a person's name should be 2–6 words,
    all starting with a capital letter, no digits.
    """
    if not text:
        return False
    if re.search(r"\d", text):
        return False  # contains year or number — not a name
    words = text.split()
    if not (2 <= len(words) <= 6):
        return False
    # Each word should start with an uppercase letter (allow "de", "la", "van")
    if not all(w[0].isupper() or w.lower() in ("de", "la", "van", "von", "del") for w in words):
        return False
    return True


def _extract_years(title: str):
    """Extract (birth_year, death_year) from a string like '(1938-2026)'."""
    m = re.search(r"\((\d{4})\s*[-–]\s*(\d{4})\)", title)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _source_from_title(title: str) -> str:
    """Try to identify the news source from the title suffix."""
    for src in ("Mercury News", "Palo Alto Online", "Legacy", "SFGate", "SF Chronicle"):
        if src.lower() in title.lower():
            return src
    return "Google News"
