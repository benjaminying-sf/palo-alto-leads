from typing import List, Optional
"""
Federal Bankruptcy Court — Chapter 13 pre-foreclosure signal scraper.

Uses the CourtListener free API (courtlistener.com) to find recent
bankruptcy filings in the Northern District of California (which covers
Palo Alto / Santa Clara County).

Why bankruptcy = motivated seller signal:
  Chapter 13 ("Wage Earner's Plan") lets homeowners restructure debts
  and stop a pending foreclosure. When someone files Chapter 13 in Palo Alto,
  they are almost certainly a distressed homeowner.

  Chapter 7 ("Liquidation") can also include homeowners who can no longer
  afford their mortgage and need to sell quickly.

Setup (ONE-TIME, FREE):
  1. Go to https://www.courtlistener.com/register/
  2. Create a free account (takes 2 minutes)
  3. Go to https://www.courtlistener.com/profile/api-keys/
  4. Click "Add Token" — copy the token
  5. Add to your .env file:  COURTLISTENER_TOKEN=your_token_here

Without a token the scraper will try unauthenticated access (rate limited
but may return some results).
"""

import logging
import re
import urllib.parse
from datetime import datetime, timedelta

import requests

import config
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

COURTLISTENER_API = "https://www.courtlistener.com/api/rest/v4"

# Northern District of California = Palo Alto's bankruptcy court
# canb = CA Northern Bankruptcy
COURT_CODE = "canb"

# Chapter codes: 7 (liquidation), 11 (reorganization), 13 (wage earner plan)
# 13 is most common for homeowners trying to save their house
CHAPTER_CODES = ["13", "7"]


class BankruptcyScraper(BaseScraper):
    """
    Finds Chapter 13/7 bankruptcy filings in the Northern District of CA
    as a pre-foreclosure / motivated seller signal.
    """

    def run(self, days_back: int = 7) -> List[dict]:
        token = config.COURTLISTENER_TOKEN
        if not token:
            logger.warning(
                "No COURTLISTENER_TOKEN in .env — bankruptcy scraper will try "
                "unauthenticated (rate limited). For reliable results, get a FREE "
                "token at https://www.courtlistener.com/register/"
            )

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        start_str = start_date.strftime("%Y-%m-%d")

        logger.info(
            "Searching CourtListener for Chapter 13/7 bankruptcy filings since %s "
            "(Northern District CA — covers Palo Alto)...",
            start_str,
        )

        raw_dockets = self._fetch_dockets(start_str, token)
        logger.info("CourtListener returned %d bankruptcy dockets", len(raw_dockets))

        leads = [lead for d in raw_dockets if (lead := self._to_lead(d))]
        logger.info("Bankruptcy scraper: %d leads (cross-reference with property records)", len(leads))
        return leads

    # ── API calls ─────────────────────────────────────────────────────────────

    def _fetch_dockets(self, filed_after: str, token: Optional[str]) -> List[dict]:
        """Fetch recent bankruptcy dockets from CourtListener."""
        # Use minimal, API-friendly headers — the browser-mimicking headers from
        # config.HEADERS cause CourtListener to hang/timeout.
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        }
        if token:
            headers["Authorization"] = f"Token {token}"

        dockets = []
        url = f"{COURTLISTENER_API}/dockets/"

        params = {
            "court": COURT_CODE,
            "date_filed__gte": filed_after,
            "order_by": "-date_filed",
            "page_size": 100,
        }

        # CourtListener API is slow (often 50-70 seconds) and has rate limits
        # on free tier. Use a generous timeout; the weekly scheduler only calls
        # this once per week so throttling won't be an issue.
        CL_TIMEOUT = max(config.REQUEST_TIMEOUT, 120)

        try:
            while url:
                resp = requests.get(
                    url,
                    headers=headers,
                    params=params if "?" not in url else None,
                    timeout=CL_TIMEOUT,
                )

                if resp.status_code == 401:
                    logger.warning(
                        "CourtListener API returned 401 Unauthorized. "
                        "Add a free token to .env: COURTLISTENER_TOKEN=your_token "
                        "Get one free at https://www.courtlistener.com/register/"
                    )
                    return []

                resp.raise_for_status()
                data = resp.json()

                results = data.get("results", [])
                dockets.extend(results)

                # Pagination
                url = data.get("next")
                params = None  # next URL already has params embedded

                if len(dockets) >= 500:
                    break

        except requests.RequestException as exc:
            logger.warning("CourtListener API request failed: %s", exc)

        return dockets

    # ── Lead builder ──────────────────────────────────────────────────────────

    def _to_lead(self, docket: dict) -> Optional[dict]:
        """Convert a bankruptcy docket to a motivated seller lead."""
        case_name = docket.get("case_name", "").strip()
        if not case_name:
            return None

        # Bankruptcy case names are "In re John Smith" or "In re John & Jane Smith"
        # Extract the debtor name
        debtor = re.sub(r"^in re\s+", "", case_name, flags=re.IGNORECASE).strip()
        if not debtor:
            debtor = case_name

        case_number = docket.get("docket_number", "").strip()
        filed_date = (docket.get("date_filed") or "").strip()
        chapter = self._extract_chapter(case_name, docket)

        court_url = (
            f"https://www.courtlistener.com{docket['absolute_url']}"
            if docket.get("absolute_url")
            else "https://www.courtlistener.com/recap/"
        )

        chapter_label = {
            "7": "Chapter 7 (Liquidation)",
            "11": "Chapter 11 (Reorganization)",
            "13": "Chapter 13 (Save-the-Home Plan)",
        }.get(chapter, f"Chapter {chapter}")

        # Address is inside PACER court documents (requires paid access).
        # Instead we generate one-click lookup links so the user can find
        # the address and confirm Palo Alto property ownership in ~30 seconds.
        google_url = (
            "https://www.google.com/search?q="
            + urllib.parse.quote_plus(f'"{debtor}" "Palo Alto" property home bankruptcy')
        )
        tps_url = (
            "https://www.truepeoplesearch.com/results?name="
            + urllib.parse.quote(debtor)
            + "&citystatezip=Palo+Alto%2C+CA"
        )

        return {
            "lead_type": config.LEAD_TYPE_FORECLOSURE,
            "address": "",  # Not in public docket header — use lookup links below
            "zip_code": "",
            "owner_name": debtor,
            "contact_name": debtor,
            "contact_phone": "",
            "contact_email": "",
            "contact_role": "Bankruptcy Debtor",
            "filing_date": filed_date,
            "case_number": case_number,
            "extra_info": (
                f"{chapter_label} — Northern District CA (covers Palo Alto/Santa Clara County). "
                f"Case {case_number} filed {filed_date}. "
                "Use the links below to find their address and confirm Palo Alto property ownership."
            ),
            "google_search_url": google_url,
            "tps_url": tps_url,
            "court_url": court_url,
        }

    @staticmethod
    def _extract_chapter(case_name: str, docket: dict) -> str:
        """Try to determine bankruptcy chapter from available data."""
        # Some docket records include the chapter in the case name or fields
        chapter_field = str(docket.get("chapter", "") or "")
        if chapter_field:
            return chapter_field

        # Look for "Chapter 13" or "Ch 13" in case name
        m = re.search(r"ch(?:apter)?\s*(\d+)", case_name, re.IGNORECASE)
        if m:
            return m.group(1)

        # Default to 13 (most common for homeowners)
        return "13"
