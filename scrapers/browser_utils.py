"""
Safari WebDriver utilities — uses macOS's built-in SafariDriver.

NO installation required. Safari is already on your Mac.
One-time setup (2 minutes):
  1. Open Safari
  2. Safari menu → Settings → Advanced tab → tick "Show Develop menu in menu bar"
  3. In the menu bar: Develop → tick "Allow Remote Automation"
  4. Open Terminal and run:  safaridriver --enable

After that, the automated scrapers can control Safari to access
JavaScript-heavy county websites that block regular Python requests.
"""
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# How long to wait for a page / element to load (seconds)
PAGE_LOAD_WAIT = 15
ELEMENT_WAIT = 10


def get_safari_driver():
    """
    Return a configured Safari WebDriver instance, or None if Safari
    automation is not enabled.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.safari.options import Options as SafariOptions

        options = SafariOptions()
        driver = webdriver.Safari(options=options)
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(15)
        return driver
    except Exception as exc:
        msg = str(exc)
        if "not enabled" in msg.lower() or "remote automation" in msg.lower():
            logger.warning(
                "Safari Remote Automation is not enabled. "
                "One-time setup: Open Safari → Develop menu → "
                "Allow Remote Automation. Then run: safaridriver --enable"
            )
        else:
            logger.warning("Could not start Safari WebDriver: %s", exc)
        return None


def wait_for_element(driver, by, selector: str, timeout: int = ELEMENT_WAIT):
    """Wait for a DOM element to appear and return it, or None."""
    try:
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, selector))
        )
    except Exception:
        return None


def wait_for_text(driver, by, selector: str, timeout: int = ELEMENT_WAIT):
    """Wait for an element to contain any text, return element or None."""
    try:
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        return WebDriverWait(driver, timeout).until(
            EC.text_to_be_present_in_element((by, selector), "")
        )
    except Exception:
        return None


def page_source_after_load(driver, url: str, extra_wait: float = 3.0) -> str:
    """
    Navigate to URL, wait for Angular/JS to finish rendering,
    then return page source HTML.
    """
    try:
        driver.get(url)
        time.sleep(extra_wait)  # Let JS framework initialize
        return driver.page_source
    except Exception as exc:
        logger.warning("Safari navigation to %s failed: %s", url, exc)
        return ""


def is_safari_automation_available() -> bool:
    """Quick check — returns True if Safari WebDriver can be started."""
    driver = None
    try:
        from selenium import webdriver
        driver = webdriver.Safari()
        driver.quit()
        return True
    except Exception:
        return False
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
