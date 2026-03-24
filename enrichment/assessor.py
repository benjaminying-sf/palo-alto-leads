from typing import List, Optional
"""
Santa Clara County Assessor enrichment.

Given a property address or APN, looks up:
  - Confirmed owner name
  - Owner mailing address (useful if they moved away)
  - Assessed land value
  - Assessed improvement value
  - Total assessed value
  - Parcel number (APN)

Data source: https://eaas.sccgov.org/ (public, no login required)

For Palo Alto, assessed value is often 20-50% of market value due to
Prop 13. Multiply by 3-5x to estimate market value.
"""

import logging
import re
import time

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

ASSESSOR_SEARCH = "https://eaas.sccgov.org/wps/portal/assessor/aa"


def find_palo_alto_property_by_name(owner_name: str) -> Optional[dict]:
    """
    Search the Santa Clara County Assessor by OWNER NAME.

    Used by the probate scraper to check whether a decedent owned
    property in Palo Alto. Returns a dict with address + assessed value
    if a Palo Alto property is found, otherwise returns None.

    The Assessor's public GIS API supports name-based searches:
      https://gis.sccgov.org/server/rest/services/BaseMaps/Parcels/MapServer/0/query

    This is a public ArcGIS endpoint — no login required.
    """
    if not owner_name:
        return None

    # Use the county's public ArcGIS parcel layer (name search)
    GIS_URL = (
        "https://gis.sccgov.org/server/rest/services/BaseMaps/Parcels/MapServer/0/query"
    )

    # Normalize name: strip commas/extra spaces, uppercase for matching
    name_upper = owner_name.upper().strip()
    # The assessor stores names as "LASTNAME FIRSTNAME" or "LASTNAME, FIRSTNAME"
    # Try a LIKE query covering both formats
    where_clause = (
        f"UPPER(OWNER_NAME) LIKE '%{name_upper}%'"
    )

    params = {
        "where": where_clause,
        "outFields": "OWNER_NAME,SITUS_ADDR,SITUS_CITY,APN,NET_VALUE",
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": 20,
    }

    try:
        session = requests.Session()
        session.headers.update(config.HEADERS)
        resp = session.get(GIS_URL, params=params, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
        if not features:
            logger.debug("Assessor name search: no properties found for '%s'", owner_name)
            return None

        # Filter to Palo Alto properties only
        for feat in features:
            attrs = feat.get("attributes", {})
            city = (attrs.get("SITUS_CITY") or "").upper().strip()
            addr = (attrs.get("SITUS_ADDR") or "").strip()

            # Check city field or zip code in address
            is_pa = city in ("PALO ALTO", "PA") or any(
                z in addr for z in config.PALO_ALTO_ZIPS
            )
            if is_pa:
                net_val = attrs.get("NET_VALUE") or ""
                assessed_str = f"${int(net_val):,}" if net_val else ""
                logger.info(
                    "Assessor name match: '%s' owns Palo Alto property at %s",
                    owner_name, addr,
                )
                return {
                    "address": addr,
                    "zip_code": _zip_from_address(addr),
                    "city": city,
                    "owner_name": (attrs.get("OWNER_NAME") or owner_name).strip(),
                    "apn": (attrs.get("APN") or "").strip(),
                    "assessed_value": assessed_str,
                }

        logger.debug(
            "Assessor name search: '%s' found %d properties but none in Palo Alto",
            owner_name, len(features)
        )
        return None

    except Exception as exc:
        logger.debug("Assessor name search failed for '%s': %s", owner_name, exc)
        return None


def _zip_from_address(address: str) -> str:
    m = re.search(r"\b(9430[1-6])\b", address)
    return m.group(1) if m else ""


def enrich_lead(lead: dict) -> dict:
    """
    Attempt to enrich a lead dict with Assessor data.
    Returns the lead dict (modified in place) with extra fields filled in.
    """
    address = lead.get("address", "").strip()
    apn = lead.get("apn", "").strip()

    if not address and not apn:
        return lead

    logger.debug("Assessor lookup for: %s / APN: %s", address, apn)
    data = _lookup(address=address, apn=apn)

    if data:
        # Only fill in fields that are blank
        if not lead.get("owner_name") and data.get("owner_name"):
            lead["owner_name"] = data["owner_name"]
        if not lead.get("owner_mailing"):
            lead["owner_mailing"] = data.get("owner_mailing", "")
        if not lead.get("apn") and data.get("apn"):
            lead["apn"] = data["apn"]
        lead["assessed_value"] = data.get("assessed_value", "")

    return lead


def _lookup(address: str = "", apn: str = "") -> Optional[dict]:
    """
    Query the Santa Clara County Assessor's public property search.

    The Assessor's eAAS system at eaas.sccgov.org supports:
      - Address search
      - APN (Assessor's Parcel Number) search

    NOTE: The eAAS portal uses an IBM WebSphere portal with generated URLs.
    The simplest entry point is the address search form. If the portal changes,
    you can alternatively use the County's GIS API:
      https://gis.sccgov.org/server/rest/services
    or the Assessor's public data download (updated annually).
    """
    session = requests.Session()
    session.headers.update(config.HEADERS)

    try:
        # Step 1: Load the search form
        resp = session.get(ASSESSOR_SEARCH, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Find the search form
        form = soup.find("form")
        if not form:
            logger.debug("Assessor: no form found on page")
            return None

        # Collect hidden fields
        hidden = {
            inp["name"]: inp.get("value", "")
            for inp in form.select("input[type=hidden]")
            if inp.get("name")
        }

        # Determine action URL
        action = form.get("action", ASSESSOR_SEARCH)
        if not action.startswith("http"):
            action = "https://eaas.sccgov.org" + action

        # Step 2: Submit the address or APN search
        if apn:
            payload = {**hidden, "searchType": "APN", "apn": apn.replace("-", "")}
        else:
            # Use just the street number and name (no city/zip needed)
            street_part = _street_only(address)
            payload = {**hidden, "searchType": "address", "situs": street_part}

        time.sleep(config.REQUEST_DELAY_SECONDS)
        results_resp = session.post(action, data=payload, timeout=config.REQUEST_TIMEOUT)
        results_resp.raise_for_status()

        return _parse_assessor_result(results_resp.text)

    except requests.RequestException as exc:
        logger.debug("Assessor lookup failed: %s", exc)
        return None
    except Exception as exc:
        logger.debug("Assessor parse error: %s", exc)
        return None


def _parse_assessor_result(html: str) -> Optional[dict]:
    """Parse the Assessor result page and extract property details."""
    soup = BeautifulSoup(html, "lxml")

    # The Assessor result page typically shows a table of property details.
    # Common patterns: definition lists (<dl><dt>Field</dt><dd>Value</dd>),
    # or label/value pairs in a table.

    result = {}

    # Try definition list first
    for dt in soup.find_all("dt"):
        label = dt.get_text(strip=True).lower()
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        value = dd.get_text(" ", strip=True)

        if "owner" in label and "name" in label:
            result["owner_name"] = value
        elif "mail" in label and "address" in label:
            result["owner_mailing"] = value
        elif "parcel" in label or "apn" in label:
            result["apn"] = value
        elif "assessed" in label and "value" in label:
            result["assessed_value"] = value
        elif "net" in label and "value" in label:
            if not result.get("assessed_value"):
                result["assessed_value"] = value

    if result:
        return result

    # Fallback: scrape all <td> label/value pairs
    rows = soup.find_all("tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).lower()
            value = cells[1].get_text(" ", strip=True)

            if "owner" in label:
                result["owner_name"] = value
            elif "mail" in label:
                result["owner_mailing"] = value
            elif "parcel" in label or "apn" in label:
                result["apn"] = value
            elif "assess" in label and "value" in label:
                result["assessed_value"] = value

    return result if result else None


def _street_only(address: str) -> str:
    """Strip city/state/zip from an address, keep just the street portion."""
    # Remove zip code
    address = re.sub(r"\b9430\d\b", "", address)
    # Remove state abbreviation
    address = re.sub(r"\bCA\b", "", address, flags=re.I)
    # Remove city name
    address = re.sub(r"\bPalo Alto\b", "", address, flags=re.I)
    return " ".join(address.split()).strip().rstrip(",")
