from typing import List, Optional
"""
Santa Clara County Tax Collector — Tax-Defaulted Property scraper.

Data sources tried in order:
  1. DTAC public auction page (correct county URL)
     https://dtac.santaclaracounty.gov/taxes/public-auction-tax-defaulted-properties
  2. Santa Clara County Open Data portal (Socrata API)
     https://data.sccgov.org
  3. Bid4Assets auction listings (third-party but lists the same properties)
     https://www.bid4assets.com/santaclara
"""

import logging
import re
import time
from datetime import datetime
from io import StringIO, BytesIO

import requests
from bs4 import BeautifulSoup

import config
from scrapers.base import BaseScraper
from scrapers.browser_utils import get_safari_driver, page_source_after_load

logger = logging.getLogger(__name__)

DTAC_URL = "https://dtac.santaclaracounty.gov/taxes/public-auction-tax-defaulted-properties"
BID4ASSETS_URL = "https://www.bid4assets.com/santaclara"
# Santa Clara open data — search for tax default datasets
OPEN_DATA_SEARCH = "https://data.sccgov.org/api/views/metadata/v1?method=getByDomain&limit=200"


class TaxDefaultScraper(BaseScraper):
    """Finds Palo Alto properties on the Santa Clara County tax-default list."""

    def run(self, days_back: int = 7) -> List[dict]:
        logger.info("Fetching Santa Clara County tax-defaulted property list...")

        raw = self._fetch_dtac()

        # DTAC blocks Python requests (403) — try Safari WebDriver as fallback
        if not raw and config.USE_SAFARI_AUTOMATION:
            logger.info("DTAC blocked requests — trying Safari WebDriver...")
            raw = self._fetch_dtac_via_safari()

        if not raw:
            raw = self._fetch_bid4assets()

        logger.info("Found %d raw tax-default records", len(raw))
        leads = [lead for r in raw if (lead := self._to_lead(r))]
        logger.info("Tax-default scraper: %d Palo Alto leads", len(leads))
        return leads

    # ── DTAC (primary) ────────────────────────────────────────────────────────

    def _fetch_dtac(self) -> List[dict]:
        """
        Fetch the DTAC tax-defaulted property auction page.
        The county lists properties available for tax sale on this page,
        sometimes with a downloadable CSV/Excel or inline table.
        """
        try:
            resp = self._get(DTAC_URL)
            if not resp:
                return []

            soup = BeautifulSoup(resp.text, "lxml")

            # Look for a downloadable file link first
            file_link = soup.find(
                "a",
                href=re.compile(r"\.(csv|xls|xlsx|pdf)", re.I),
            )
            if file_link:
                href = file_link["href"]
                if not href.startswith("http"):
                    href = "https://dtac.santaclaracounty.gov" + href
                if not href.lower().endswith(".pdf"):
                    return self._download_file(href)

            # Look for an inline HTML table
            tables = soup.find_all("table")
            for table in tables:
                records = self._parse_html_table(table)
                if records:
                    return records

            # No table or file found — log the page text for debugging
            logger.info(
                "DTAC page loaded but no downloadable list found. "
                "The county may only list properties when an auction is scheduled. "
                "Visit %s to check manually.", DTAC_URL
            )
            return []

        except Exception as exc:
            logger.warning("DTAC fetch failed: %s", exc)
            return []

    # ── DTAC via Safari WebDriver ─────────────────────────────────────────────

    def _fetch_dtac_via_safari(self) -> List[dict]:
        """
        Open the DTAC tax auction page using real Safari.
        The county blocks Python requests but a real browser works.

        Requires one-time setup:
          Safari → Develop → Allow Remote Automation
          Terminal: safaridriver --enable
        """
        driver = get_safari_driver()
        if not driver:
            return []

        records = []
        try:
            logger.info("Safari opening DTAC tax auction page...")
            html = page_source_after_load(driver, DTAC_URL, extra_wait=4.0)

            if not html:
                return []

            soup = BeautifulSoup(html, "lxml")

            # Look for a downloadable file link
            file_link = soup.find(
                "a",
                href=re.compile(r"\.(csv|xls|xlsx)", re.I),
            )
            if file_link:
                href = file_link["href"]
                if not href.startswith("http"):
                    href = "https://dtac.santaclaracounty.gov" + href
                logger.info("Found downloadable file at %s", href)
                # Download with Safari session cookies
                try:
                    cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
                    resp = requests.get(
                        href,
                        headers=config.HEADERS,
                        cookies=cookies,
                        timeout=30,
                    )
                    resp.raise_for_status()
                    if href.lower().endswith(".csv"):
                        import pandas as pd
                        import io
                        df = pd.read_csv(io.StringIO(resp.text), dtype=str)
                    else:
                        import pandas as pd
                        import io
                        df = pd.read_excel(io.BytesIO(resp.content), dtype=str)

                    df.columns = [str(c).strip().lower() for c in df.columns]
                    for _, row in df.iterrows():
                        address = (
                            row.get("situs address") or row.get("property address")
                            or row.get("address") or ""
                        ).strip()
                        if self._is_palo_alto(address):
                            owner = (
                                row.get("assessee name") or row.get("owner name")
                                or row.get("owner") or ""
                            ).strip()
                            records.append({
                                "address": address,
                                "owner_name": owner,
                                "amount_owed": (
                                    row.get("total due") or row.get("amount due") or ""
                                ).strip(),
                                "year_defaulted": (
                                    row.get("default year") or row.get("tax year") or ""
                                ).strip(),
                                "apn": (row.get("apn") or row.get("parcel") or "").strip(),
                            })
                    return records
                except Exception as dl_exc:
                    logger.warning("Could not download DTAC file: %s", dl_exc)

            # No file link — try parsing an inline table
            for table in soup.find_all("table"):
                records.extend(self._parse_html_table(table))
                if records:
                    break

            if not records:
                logger.info(
                    "DTAC page loaded via Safari but no property list found. "
                    "The county only posts the list before their annual auction (usually Feb–May). "
                    "Check manually: %s",
                    DTAC_URL,
                )

        except Exception as exc:
            logger.warning("Safari DTAC scrape failed: %s", exc)
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        return records

    # ── Bid4Assets (fallback) ─────────────────────────────────────────────────

    def _fetch_bid4assets(self) -> List[dict]:
        """
        Bid4Assets hosts the Santa Clara County tax-sale auction.
        Their listing page shows properties with addresses.
        """
        try:
            resp = self._get(BID4ASSETS_URL)
            if not resp:
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            records = []

            # Bid4Assets renders property cards or a table
            # Try table first
            for table in soup.find_all("table"):
                records.extend(self._parse_html_table(table))

            if not records:
                # Try property cards / divs
                for card in soup.select(".auction-item, .property-card, [class*='auction'], [class*='property']"):
                    text = card.get_text(" ", strip=True)
                    address_match = re.search(
                        r"\d+\s+[\w\s]+(?:St|Ave|Blvd|Dr|Ln|Rd|Way|Ct|Pl|Ter|Cir)\b[^,]*,?\s*(?:Palo Alto)?",
                        text, re.I
                    )
                    if address_match:
                        address = address_match.group(0).strip()
                        if self._is_palo_alto(address):
                            records.append({
                                "address": address,
                                "owner_name": "",
                                "amount_owed": "",
                                "year_defaulted": "",
                                "apn": "",
                            })

            logger.info("Bid4Assets returned %d records", len(records))
            return records

        except Exception as exc:
            logger.warning("Bid4Assets fetch failed: %s", exc)
            return []

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _download_file(self, url: str) -> List[dict]:
        """Download a CSV or Excel file and parse it."""
        try:
            import pandas as pd

            resp = self._get(url)
            if not resp:
                return []

            if url.lower().endswith(".csv"):
                df = pd.read_csv(StringIO(resp.text), dtype=str)
            else:
                df = pd.read_excel(BytesIO(resp.content), dtype=str)

            df.columns = [str(c).strip().lower() for c in df.columns]
            records = []

            for _, row in df.iterrows():
                address = (
                    row.get("situs address") or row.get("property address")
                    or row.get("address") or ""
                ).strip()

                if not self._is_palo_alto(address):
                    continue

                owner = (
                    row.get("assessee name") or row.get("owner name")
                    or row.get("owner") or ""
                ).strip()

                records.append({
                    "address": address,
                    "owner_name": owner,
                    "amount_owed": (
                        row.get("total due") or row.get("amount due")
                        or row.get("amount owed") or ""
                    ).strip(),
                    "year_defaulted": (
                        row.get("default year") or row.get("tax year") or ""
                    ).strip(),
                    "apn": (row.get("apn") or row.get("parcel") or "").strip(),
                })

            return records

        except Exception as exc:
            logger.warning("File download/parse failed from %s: %s", url, exc)
            return []

    def _parse_html_table(self, table) -> List[dict]:
        """Parse an HTML table for tax-default records."""
        rows = table.find_all("tr")
        if not rows:
            return []

        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        records = []

        for row in rows[1:]:
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if not cells:
                continue

            data = dict(zip(headers, cells)) if headers else {}
            address = (
                data.get("address") or data.get("property address")
                or data.get("situs") or (cells[1] if len(cells) > 1 else "")
            ).strip()

            if not self._is_palo_alto(address):
                continue

            owner = (
                data.get("owner") or data.get("assessee")
                or data.get("name") or (cells[0] if cells else "")
            ).strip()

            records.append({
                "address": address,
                "owner_name": owner,
                "amount_owed": (data.get("amount") or data.get("total due") or "").strip(),
                "year_defaulted": (data.get("year") or data.get("default year") or "").strip(),
                "apn": (data.get("apn") or data.get("parcel") or "").strip(),
            })

        return records

    def _to_lead(self, record: dict) -> Optional[dict]:
        address = record.get("address", "").strip()
        owner = record.get("owner_name", "").strip()
        if not (address or owner):
            return None

        amount = record.get("amount_owed", "")
        year_def = record.get("year_defaulted", "")

        years_late = ""
        if year_def:
            try:
                years_late = f" ({datetime.now().year - int(year_def)} years delinquent)"
            except ValueError:
                pass

        return {
            "lead_type": config.LEAD_TYPE_TAX_DEFAULT,
            "address": address,
            "zip_code": self._extract_zip(address),
            "apn": record.get("apn", ""),
            "owner_name": owner,
            "contact_name": owner,
            "contact_phone": "",
            "contact_email": "",
            "contact_role": "Property Owner (skip tracing needed for phone)",
            "filing_date": year_def,
            "amount_owed": amount,
            "extra_info": (
                f"Tax-defaulted since {year_def}{years_late}. "
                f"Amount owed: {amount}. "
                "Owner risks losing property at county auction — highly motivated to sell."
            ),
            "google_search_url": self._google_search_url(owner, address),
        }

    # ── Utilities ──────────────────────────────────────────────────────────────

    @staticmethod
    def _is_palo_alto(address: str) -> bool:
        addr_upper = address.upper()
        if config.PALO_ALTO_CITY in addr_upper:
            return True
        for z in config.PALO_ALTO_ZIPS:
            if z in addr_upper:
                return True
        return False

    @staticmethod
    def _extract_zip(address: str) -> str:
        m = re.search(r"\b(9430[1-6])\b", address)
        return m.group(1) if m else ""
