from typing import List, Optional
"""
Santa Clara County Recorder scraper — finds Notices of Default (NOD) and
Notices of Trustee Sale (NTS) recorded against Palo Alto properties.

Pre-foreclosure timeline:
  Day 0   → Borrower misses payment
  Day 90  → Lender records NOD  ← we catch it here
  Day 90-180 → Reinstatement window (borrower can still pay off)
  Day 180+ → Notice of Trustee Sale recorded  ← also caught here
  Day 180-210 → Property sold at auction

Data source: https://clerkrecorder.santaclaracounty.gov/official-records/records-search
NOTE: As of 2025, the county recorder's online search was discontinued.
NOD/NTS documents must be searched in-person or via a title company.
This scraper attempts the page anyway in case online access is restored,
and logs clear instructions for manual search if it fails.
"""

import logging
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

import config
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class RecorderScraper(BaseScraper):
    """Scrapes the Santa Clara County Recorder for pre-foreclosure documents."""

    # Document types to watch for
    DOC_TYPES = {
        "ND": "Notice of Default",
        "NTS": "Notice of Trustee Sale",
        "LPN": "Lis Pendens",  # lawsuit filed against property (sometimes divorce/debt)
    }

    def run(self, days_back: int = 7) -> List[dict]:
        leads = []
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)

        for doc_code, doc_label in self.DOC_TYPES.items():
            logger.info("Searching recorder for %s (%s)...", doc_label, doc_code)
            results = self._search_documents(doc_code, start_date, end_date)
            logger.info("  Found %d raw results for %s", len(results), doc_code)
            for doc in results:
                lead = self._to_lead(doc, doc_code, doc_label)
                if lead:
                    leads.append(lead)
            time.sleep(config.REQUEST_DELAY_SECONDS)

        logger.info("Recorder scraper: %d Palo Alto pre-foreclosure leads", len(leads))
        return leads

    # ── Private helpers ────────────────────────────────────────────────────────

    def _search_documents(
        self, doc_type: str, start: datetime, end: datetime
    ) -> List[dict]:
        """
        Submit a document-type search against the Santa Clara County Recorder
        and return a list of raw result dicts.

        NOTE: The county recorder uses an iframe-based search at ccr.sccgov.org.
        The form below targets the known POST endpoint. If the site changes its
        form structure, run the scraper with --debug to see what HTML is returned
        and update the field names below accordingly.
        """
        session = requests.Session()
        session.headers.update(config.HEADERS)

        RECORDER_URL = "https://clerkrecorder.santaclaracounty.gov/official-records/records-search"

        try:
            # Step 1: Load the search page to get any session cookies / CSRF tokens
            home_resp = session.get(
                RECORDER_URL,
                timeout=config.REQUEST_TIMEOUT,
            )
            home_resp.raise_for_status()
            soup = BeautifulSoup(home_resp.text, "lxml")

            # Try to find a hidden CSRF/viewstate token (common in ASP.NET sites)
            hidden_inputs = {
                inp["name"]: inp.get("value", "")
                for inp in soup.select("input[type=hidden]")
                if inp.get("name")
            }

            # Step 2: Build the search payload
            payload = {
                **hidden_inputs,
                "docType": doc_type,
                "startDate": start.strftime("%m/%d/%Y"),
                "endDate": end.strftime("%m/%d/%Y"),
                "searchType": "document",
            }

            # Step 3: Submit the search
            search_resp = session.post(
                RECORDER_URL,
                data=payload,
                timeout=config.REQUEST_TIMEOUT,
            )
            search_resp.raise_for_status()

            return self._parse_results(search_resp.text, doc_type)

        except requests.RequestException as exc:
            logger.warning(
                "Recorder request failed for %s: %s. "
                "The Santa Clara County Recorder discontinued online search. "
                "To get NOD data: visit https://clerkrecorder.santaclaracounty.gov "
                "in person, or use PropStream (free 7-day trial) for automated NOD data. "
                "You can also use --import-csv to manually add any leads you find.",
                doc_type, exc,
            )
            return []

    def _parse_results(self, html: str, doc_type: str) -> List[dict]:
        """Parse the HTML results table from the recorder search."""
        soup = BeautifulSoup(html, "lxml")
        docs = []

        # The recorder typically renders results in a <table> with class 'results'
        # Adjust the selector below if the site structure changes.
        table = soup.find("table", {"class": lambda c: c and "result" in c.lower()})
        if not table:
            # Fallback: look for any table with multiple rows
            tables = soup.find_all("table")
            table = next(
                (t for t in tables if len(t.find_all("tr")) > 2), None
            )

        if not table:
            logger.debug("No results table found in recorder response for %s", doc_type)
            return []

        rows = table.find_all("tr")
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]

        for row in rows[1:]:
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if len(cells) < 3:
                continue

            # Map cells to a dict using header names when available
            data = dict(zip(headers, cells)) if headers else {}

            # Attempt to extract key fields — adjust keys to match actual headers
            address = (
                data.get("property address")
                or data.get("address")
                or data.get("situs")
                or ""
            )
            grantor = (
                data.get("grantor")
                or data.get("trustor")
                or data.get("borrower")
                or (cells[1] if len(cells) > 1 else "")
            )
            doc_number = (
                data.get("document #")
                or data.get("doc number")
                or data.get("instrument")
                or (cells[0] if cells else "")
            )
            recorded_date = (
                data.get("recorded date")
                or data.get("record date")
                or data.get("date")
                or ""
            )
            trustee = (
                data.get("grantee")
                or data.get("trustee")
                or data.get("beneficiary")
                or ""
            )

            # Only keep results for Palo Alto
            if not self._is_palo_alto(address):
                continue

            docs.append({
                "doc_type": doc_type,
                "address": self._clean_address(address),
                "grantor": grantor.strip(),
                "doc_number": doc_number.strip(),
                "recorded_date": recorded_date.strip(),
                "trustee": trustee.strip(),
                "raw": data,
            })

        return docs

    def _to_lead(self, doc: dict, doc_code: str, doc_label: str) -> Optional[dict]:
        """Convert a raw recorder document to a structured lead dict."""
        address = doc.get("address", "").strip()
        if not address:
            return None

        owner = doc.get("grantor", "Unknown Owner")
        zip_code = self._extract_zip(address)

        # The trustee named on the NOD is a legitimate contact
        trustee = doc.get("trustee", "")
        trustee_phone = self._extract_phone(trustee)

        return {
            "lead_type": config.LEAD_TYPE_FORECLOSURE,
            "address": address,
            "zip_code": zip_code,
            "owner_name": owner,
            "contact_name": trustee or "See document",
            "contact_phone": trustee_phone,
            "contact_email": "",
            "contact_role": f"Trustee (from {doc_label})",
            "filing_date": doc.get("recorded_date", ""),
            "doc_number": doc.get("doc_number", ""),
            "extra_info": f"{doc_label} — Doc # {doc.get('doc_number', '')}",
            "google_search_url": self._google_search_url(owner, address),
        }

    # ── Utilities ──────────────────────────────────────────────────────────────

    def _is_palo_alto(self, address: str) -> bool:
        addr_upper = address.upper()
        if config.PALO_ALTO_CITY in addr_upper:
            return True
        for z in config.PALO_ALTO_ZIPS:
            if z in addr_upper:
                return True
        return False

    @staticmethod
    def _clean_address(raw: str) -> str:
        return " ".join(raw.split()).strip()

    @staticmethod
    def _extract_zip(address: str) -> str:
        import re
        m = re.search(r"\b(9430[1-6])\b", address)
        return m.group(1) if m else ""

    @staticmethod
    def _extract_phone(text: str) -> str:
        import re
        m = re.search(r"(\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4})", text)
        return m.group(1) if m else ""

    @staticmethod
    def _google_search_url(name: str, address: str) -> str:
        import urllib.parse
        query = urllib.parse.quote_plus(f'"{name}" "{address}" phone contact')
        return f"https://www.google.com/search?q={query}"
