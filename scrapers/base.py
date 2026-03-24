"""
Shared base class for all scrapers.
"""
import logging
import time

from typing import List, Optional

import requests

import config

logger = logging.getLogger(__name__)


class BaseScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(config.HEADERS)

    def _get(self, url: str, **kwargs) -> Optional[requests.Response]:
        try:
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT, **kwargs)
            resp.raise_for_status()
            time.sleep(config.REQUEST_DELAY_SECONDS)
            return resp
        except requests.RequestException as exc:
            logger.warning("GET %s failed: %s", url, exc)
            return None

    def _post(self, url: str, data: dict, **kwargs) -> Optional[requests.Response]:
        try:
            resp = self.session.post(url, data=data, timeout=config.REQUEST_TIMEOUT, **kwargs)
            resp.raise_for_status()
            time.sleep(config.REQUEST_DELAY_SECONDS)
            return resp
        except requests.RequestException as exc:
            logger.warning("POST %s failed: %s", url, exc)
            return None

    @staticmethod
    def _google_search_url(name: str, address: str) -> str:
        import urllib.parse
        query = urllib.parse.quote_plus(f'"{name}" "{address}" contact phone')
        return f"https://www.google.com/search?q={query}"

    def run(self, days_back: int = 7) -> List[dict]:
        raise NotImplementedError
