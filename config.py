import os
from dotenv import load_dotenv

load_dotenv()

# ── Palo Alto geography ────────────────────────────────────────────────────────
PALO_ALTO_ZIPS = ["94301", "94302", "94303", "94304", "94305", "94306"]
PALO_ALTO_CITY = "PALO ALTO"

# ── Santa Clara County public record URLs ─────────────────────────────────────
RECORDER_SEARCH_URL = "https://ccr.sccgov.org/recorder/web/"
COURT_CASE_SEARCH_URL = "https://www.scscourt.org/online_services/online_services.shtml"
COURT_INDEX_URL = "https://icefiling.sccgov.org/PublicAccess/"
ASSESSOR_SEARCH_URL = "https://eaas.sccgov.org/wps/portal/assessor"
TAX_COLLECTOR_URL = "https://www.sccgov.org/sites/tax/Pages/Tax-Defaulted-Property.aspx"

# ── Safari WebDriver automation ───────────────────────────────────────────────
# Set USE_SAFARI_AUTOMATION=true in .env to enable browser-based scraping.
# One-time setup: Safari → Develop → Allow Remote Automation
# Then run in Terminal:  safaridriver --enable
# After setup, Safari will briefly open each Sunday to scrape the county sites.
USE_SAFARI_AUTOMATION = os.getenv("USE_SAFARI_AUTOMATION", "false").lower() == "true"

# ── CourtListener (free bankruptcy API) ───────────────────────────────────────
# Free account at https://www.courtlistener.com/register/
# Get token at https://www.courtlistener.com/profile/api-keys/
COURTLISTENER_TOKEN = os.getenv("COURTLISTENER_TOKEN", "")

# ── Email ──────────────────────────────────────────────────────────────────────
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# ── Scheduler ─────────────────────────────────────────────────────────────────
REPORT_DAY = os.getenv("REPORT_DAY", "sunday")
REPORT_HOUR = int(os.getenv("REPORT_HOUR", "18"))
REPORT_MINUTE = int(os.getenv("REPORT_MINUTE", "0"))

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "leads.db")
REPORTS_DIR = os.path.join(BASE_DIR, "data", "reports")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

# ── Scraping ──────────────────────────────────────────────────────────────────
REQUEST_DELAY_SECONDS = 2
REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

# ── Lead types ────────────────────────────────────────────────────────────────
LEAD_TYPE_PROBATE = "probate"
LEAD_TYPE_FORECLOSURE = "foreclosure"
LEAD_TYPE_TAX_DEFAULT = "tax_default"
LEAD_TYPE_DIVORCE = "divorce"

LEAD_TYPE_LABELS = {
    LEAD_TYPE_PROBATE: "Probate / Estate",
    LEAD_TYPE_FORECLOSURE: "Pre-Foreclosure (NOD)",
    LEAD_TYPE_TAX_DEFAULT: "Tax Delinquent",
    LEAD_TYPE_DIVORCE: "Divorce / Dissolution",
}

LEAD_TYPE_COLORS = {
    LEAD_TYPE_PROBATE: "#3B82F6",       # blue
    LEAD_TYPE_FORECLOSURE: "#EF4444",   # red
    LEAD_TYPE_TAX_DEFAULT: "#F59E0B",   # amber
    LEAD_TYPE_DIVORCE: "#8B5CF6",       # purple
}
