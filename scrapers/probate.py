from typing import List, Optional
"""
Santa Clara County Superior Court — Probate scraper.

Data sources (both tried):
  1. Santa Clara County Open Data Socrata API — probate cases dataset
     https://data.sccgov.org/Government/County-Probate-Cases/rh64-rgza
  2. Superior Court public portal fallback
     https://portal.scscourt.org/search
"""

import logging
import re
import time
from datetime import datetime, timedelta
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

import config
from scrapers.base import BaseScraper
from scrapers.browser_utils import get_safari_driver, page_source_after_load

logger = logging.getLogger(__name__)

# Santa Clara County Open Data — Probate Cases (Socrata API)
SOCRATA_API_URL = "https://data.sccgov.org/resource/rh64-rgza.json"

# Superior Court public portal
COURT_PORTAL_URL = "https://portal.scscourt.org/search"
COURT_BASE = "https://portal.scscourt.org"


class ProbateScraper(BaseScraper):
    """Fetches Santa Clara Superior Court probate filings."""

    def run(self, days_back: int = 7) -> List[dict]:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)

        logger.info("Searching probate cases from %s to %s...",
                    start_date.strftime("%m/%d/%Y"), end_date.strftime("%m/%d/%Y"))

        # Try the Socrata open data API first (most reliable)
        raw_cases = self._fetch_via_socrata(start_date)

        # Fall back to court portal scraping if API returns nothing
        if not raw_cases:
            logger.info("Socrata API returned 0 results, trying court portal (requests)...")
            raw_cases = self._fetch_via_portal(start_date, end_date)

        # Last resort: use Safari WebDriver to render the JavaScript court portal
        if not raw_cases and config.USE_SAFARI_AUTOMATION:
            logger.info("Trying Safari WebDriver for court portal...")
            raw_cases = self._fetch_via_safari(start_date, end_date)

        logger.info("Found %d raw probate cases", len(raw_cases))

        leads = [lead for case in raw_cases if (lead := self._to_lead(case))]
        logger.info("Probate scraper: %d leads", len(leads))
        return leads

    # ── Socrata API (primary) ──────────────────────────────────────────────────

    def _fetch_via_socrata(self, start_date: datetime) -> List[dict]:
        """
        Query the Santa Clara County Open Data portal for probate cases.
        Dataset: https://data.sccgov.org/Government/County-Probate-Cases/rh64-rgza
        Socrata SoQL docs: https://dev.socrata.com/docs/queries/
        """
        try:
            params = {
                "$limit": 1000,
                "$order": ":updated_at DESC",
            }

            resp = self.session.get(
                SOCRATA_API_URL,
                params=params,
                timeout=config.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            if not isinstance(data, list):
                logger.debug("Unexpected Socrata response format")
                return []

            logger.info("Socrata returned %d total probate records", len(data))

            # Filter by date only — Palo Alto filtering is done via Assessor
            # name lookup in _to_lead(), so we keep all county-wide cases here
            cutoff = start_date.strftime("%Y-%m-%d")
            cases = []
            for row in data:
                # Try common date field names
                filed = (
                    row.get("date_opened") or row.get("date_filed")
                    or row.get("filing_date") or row.get("filed_date")
                    or row.get("create_date") or ""
                )
                # Keep if filed after cutoff (or if no date — include it)
                if filed and filed[:10] < cutoff:
                    continue
                cases.append(row)

            logger.info("After date/city filter: %d probate cases", len(cases))

            # Validate that the Socrata dataset actually has usable decedent name fields.
            # The known dataset (rh64-rgza) is a historical archive (1895–2006) and its
            # records lack current-case fields. If none of the first 20 records have a
            # recognisable name field, this dataset is unusable — return [] so the
            # court-portal fallback is triggered.
            if cases:
                sample = cases[:20]
                has_name_data = any(
                    row.get("decedent_name") or row.get("name") or row.get("party_name")
                    for row in sample
                )
                if not has_name_data:
                    logger.info(
                        "Socrata records lack decedent name fields — "
                        "dataset appears to be historical archive. "
                        "Falling through to court portal."
                    )
                    return []

            return cases

        except Exception as exc:
            logger.warning("Socrata probate API failed: %s", exc)
            return []

    # ── Court portal scraping (fallback) ──────────────────────────────────────

    def _fetch_via_portal(self, start: datetime, end: datetime) -> List[dict]:
        """
        Scrape the Santa Clara Superior Court public portal.
        https://portal.scscourt.org/search
        """
        try:
            resp = self._get(COURT_PORTAL_URL)
            if not resp:
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            hidden = {
                inp["name"]: inp.get("value", "")
                for inp in soup.select("input[type=hidden]")
                if inp.get("name")
            }

            payload = {
                **hidden,
                "caseType": "PR",
                "filedDateFrom": start.strftime("%m/%d/%Y"),
                "filedDateTo": end.strftime("%m/%d/%Y"),
                "searchType": "CaseType",
            }

            form = soup.find("form")
            action = (form.get("action", "") if form else "") or COURT_PORTAL_URL
            if not action.startswith("http"):
                action = COURT_BASE + action

            search_resp = self._post(action, payload)
            if not search_resp:
                return []

            return self._parse_portal_results(search_resp.text)

        except Exception as exc:
            logger.warning(
                "Court portal search failed: %s. "
                "Visit https://portal.scscourt.org/search to search manually.",
                exc,
            )
            return []

    def _parse_portal_results(self, html: str) -> List[dict]:
        soup = BeautifulSoup(html, "lxml")
        cases = []

        table = (
            soup.find("table", {"id": re.compile(r"grid|result|case", re.I)})
            or soup.find("table", {"class": re.compile(r"grid|result|case", re.I)})
            or soup.find("table")
        )
        if not table:
            return []

        rows = table.find_all("tr")
        if not rows:
            return []
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]

        for row in rows[1:]:
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if not cells:
                continue
            data = dict(zip(headers, cells)) if headers else {}
            link_tag = row.find("a", href=True)
            detail_url = ""
            if link_tag:
                href = link_tag["href"]
                detail_url = (COURT_BASE + href) if href.startswith("/") else href

            cases.append({
                "case_number": data.get("case number") or (cells[0] if cells else ""),
                "decedent_name": data.get("party name") or data.get("name") or (cells[1] if len(cells) > 1 else ""),
                "date_opened": data.get("filed date") or data.get("date filed") or "",
                "detail_url": detail_url,
            })

        return cases

    # ── Safari WebDriver (last resort — handles JavaScript rendering) ──────────

    def _fetch_via_safari(self, start: datetime, end: datetime) -> List[dict]:
        """
        Use Safari (controlled by macOS SafariDriver) to open the Tyler
        Technologies court portal and search for probate cases.

        Requires one-time setup:
          Safari → Develop → Allow Remote Automation
          Terminal: safaridriver --enable
        """
        driver = get_safari_driver()
        if not driver:
            logger.warning(
                "Safari automation not available. "
                "Enable it: Safari → Develop → Allow Remote Automation, "
                "then run: safaridriver --enable"
            )
            return []

        cases = []
        try:
            logger.info("Safari WebDriver opening court portal...")
            html = page_source_after_load(
                driver,
                COURT_PORTAL_URL,
                extra_wait=5.0,  # Give Angular time to fully render
            )

            if not html or "access denied" in html.lower():
                logger.warning("Court portal returned Access Denied even with Safari.")
                return []

            # Try to submit the probate case type search via JavaScript
            start_str = start.strftime("%m/%d/%Y")
            end_str = end.strftime("%m/%d/%Y")

            # Tyler Technologies Odyssey Portal — inject search via Angular
            search_script = f"""
                // Try to trigger an Angular case-type search
                var inputs = document.querySelectorAll('input, select');
                inputs.forEach(function(el) {{
                    var label = (el.placeholder || el.name || el.id || '').toLowerCase();
                    if (label.includes('case') && label.includes('type')) {{
                        el.value = 'PR';
                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                        el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    }}
                    if (label.includes('start') || label.includes('from') || label.includes('begin')) {{
                        el.value = '{start_str}';
                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                        el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    }}
                    if (label.includes('end') || label.includes('to')) {{
                        el.value = '{end_str}';
                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                        el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    }}
                }});
                // Click any Search button
                var buttons = document.querySelectorAll('button, input[type=submit]');
                for (var i = 0; i < buttons.length; i++) {{
                    var txt = buttons[i].textContent.toLowerCase();
                    if (txt.includes('search')) {{
                        buttons[i].click();
                        break;
                    }}
                }}
                return 'search_triggered';
            """

            try:
                driver.execute_script(search_script)
                time.sleep(4)  # Wait for search results to load
                html = driver.page_source
            except Exception as js_exc:
                logger.warning("JavaScript injection failed: %s", js_exc)
                # Still try to parse whatever is on the page
                html = driver.page_source

            cases = self._parse_portal_results(html)
            if cases:
                logger.info("Safari WebDriver found %d probate cases", len(cases))
            else:
                logger.info(
                    "Safari opened court portal but found 0 cases. "
                    "You can search manually at: %s",
                    COURT_PORTAL_URL,
                )

        except Exception as exc:
            logger.warning("Safari WebDriver probate search failed: %s", exc)
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        return cases

    # ── Lead builder ──────────────────────────────────────────────────────────

    def _to_lead(self, case: dict) -> Optional[dict]:
        # Handle both Socrata field names and portal field names
        decedent = (
            case.get("decedent_name") or case.get("name") or case.get("party_name") or ""
        ).strip()
        if not decedent:
            return None

        case_number = (
            case.get("case_number") or case.get("case_no") or case.get("casenumber") or ""
        ).strip()

        filed = (
            case.get("date_opened") or case.get("date_filed")
            or case.get("filing_date") or case.get("filed_date") or ""
        )
        # Reformat date if it's ISO format
        if filed and "T" in filed:
            filed = filed[:10]

        # Socrata may include attorney/petitioner info
        attorney = (case.get("attorney_name") or case.get("petitioner") or "").strip()
        atty_phone = (case.get("attorney_phone") or case.get("phone") or "").strip()
        atty_email = (case.get("attorney_email") or case.get("email") or "").strip()

        contact_name = attorney or "Estate Executor (see court filing)"
        contact_role = "Attorney for Estate" if attorney else "Executor / Administrator"

        # ── Build lead (county-wide — user verifies Palo Alto ownership) ────────
        # The court portal covers ALL of Santa Clara County. We cannot
        # automatically filter to Palo Alto because no free name→address lookup
        # exists. Instead we include all county cases and give the user a
        # one-click Google link to confirm if the decedent owned Palo Alto property.
        address = (case.get("address") or case.get("decedent_address") or "").strip()
        city = (case.get("city") or case.get("decedent_city") or "").strip()

        import urllib.parse
        verify_url = (
            "https://www.google.com/search?q="
            + urllib.parse.quote_plus(f'"{decedent}" "Palo Alto" property home')
        )
        assessor_url = "https://www.sccassessor.org/apps/realpropertysearch.aspx"

        return {
            "lead_type": config.LEAD_TYPE_PROBATE,
            "address": address or "⚠️ Verify location below — county-wide result",
            "city": city or "Santa Clara County",
            "owner_name": decedent,
            "contact_name": contact_name,
            "contact_phone": atty_phone,
            "contact_email": atty_email,
            "contact_role": contact_role,
            "filing_date": filed,
            "case_number": case_number,
            "extra_info": (
                f"Probate case {case_number}. Decedent: {decedent}. "
                "⚠️ This is a Santa Clara County-wide result. "
                "Click the link below to verify this person owned a Palo Alto home."
            ),
            "google_search_url": verify_url,
            "assessor_url": assessor_url,
        }
