"""
SQLite database for storing leads and deduplication across weekly runs.
"""
import sqlite3
import hashlib
import logging
from datetime import datetime
from typing import List, Optional

import config

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS leads (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_hash       TEXT UNIQUE NOT NULL,
                lead_type       TEXT NOT NULL,
                address         TEXT,
                city            TEXT DEFAULT 'Palo Alto',
                zip_code        TEXT,
                apn             TEXT,
                owner_name      TEXT,
                owner_mailing   TEXT,
                assessed_value  TEXT,
                contact_name    TEXT,
                contact_phone   TEXT,
                contact_email   TEXT,
                contact_role    TEXT,
                extra_info      TEXT,
                filing_date     TEXT,
                doc_number      TEXT,
                case_number     TEXT,
                amount_owed     TEXT,
                google_search_url TEXT,
                first_seen      TEXT NOT NULL,
                last_seen       TEXT NOT NULL,
                times_reported  INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS weekly_runs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date        TEXT NOT NULL,
                new_leads       INTEGER DEFAULT 0,
                total_leads     INTEGER DEFAULT 0,
                email_sent      INTEGER DEFAULT 0,
                notes           TEXT
            );
        """)
    logger.info("Database initialised at %s", config.DB_PATH)


def make_lead_hash(lead_type: str, identifier: str) -> str:
    """Stable hash so the same lead isn't duplicated across weeks."""
    key = f"{lead_type}:{identifier.strip().upper()}"
    return hashlib.sha1(key.encode()).hexdigest()


def upsert_lead(lead: dict) -> bool:
    """
    Insert a new lead or update last_seen if it already exists.
    Returns True if this is a NEW lead (not seen before).
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build a stable identifier from whatever we have
    identifier = (
        lead.get("doc_number")
        or lead.get("case_number")
        or lead.get("address", "")
    )
    lead_hash = make_lead_hash(lead.get("lead_type", "unknown"), identifier)

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id, times_reported FROM leads WHERE lead_hash = ?",
            (lead_hash,),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE leads SET last_seen = ?, times_reported = times_reported + 1 WHERE lead_hash = ?",
                (now, lead_hash),
            )
            return False  # not new

        conn.execute(
            """INSERT INTO leads (
                lead_hash, lead_type, address, city, zip_code, apn,
                owner_name, owner_mailing, assessed_value,
                contact_name, contact_phone, contact_email, contact_role,
                extra_info, filing_date, doc_number, case_number,
                amount_owed, google_search_url, first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                lead_hash,
                lead.get("lead_type"),
                lead.get("address"),
                lead.get("city", "Palo Alto"),
                lead.get("zip_code"),
                lead.get("apn"),
                lead.get("owner_name"),
                lead.get("owner_mailing"),
                lead.get("assessed_value"),
                lead.get("contact_name"),
                lead.get("contact_phone"),
                lead.get("contact_email"),
                lead.get("contact_role"),
                lead.get("extra_info"),
                lead.get("filing_date"),
                lead.get("doc_number"),
                lead.get("case_number"),
                lead.get("amount_owed"),
                lead.get("google_search_url"),
                now,
                now,
            ),
        )
        return True  # new lead


def get_new_leads_since(since_date: str) -> List[dict]:
    """Return all leads first seen on or after since_date."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM leads WHERE first_seen >= ? ORDER BY lead_type, first_seen DESC",
            (since_date,),
        ).fetchall()
    return [dict(row) for row in rows]


def log_run(new_leads: int, total_leads: int, email_sent: bool, notes: str = ""):
    today = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO weekly_runs (run_date, new_leads, total_leads, email_sent, notes) VALUES (?, ?, ?, ?, ?)",
            (today, new_leads, total_leads, int(email_sent), notes),
        )
    logger.info("Run logged: %d new leads, %d total", new_leads, total_leads)
