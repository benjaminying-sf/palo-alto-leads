"""
load_leads.py — Load previously-exported JSON back into SQLite.

Called at the start of a GitHub Actions run to restore leads from the
committed JSON snapshot (since Actions runners have no persistent storage).

Reads:
  docs/leads.json  — loaded into leads table via INSERT OR IGNORE on lead_hash
  docs/runs.json   — loaded into weekly_runs table via INSERT OR IGNORE on run_date
"""
import json
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "leads.db")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
LEADS_JSON = os.path.join(DOCS_DIR, "leads.json")
RUNS_JSON = os.path.join(DOCS_DIR, "runs.json")


def init_db(conn: sqlite3.Connection):
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


def load_leads(conn: sqlite3.Connection, leads: list) -> int:
    loaded = 0
    for lead in leads:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO leads (
                    lead_hash, lead_type, address, city, zip_code, apn,
                    owner_name, owner_mailing, assessed_value,
                    contact_name, contact_phone, contact_email, contact_role,
                    extra_info, filing_date, doc_number, case_number,
                    amount_owed, google_search_url, first_seen, last_seen,
                    times_reported
                ) VALUES (
                    :lead_hash, :lead_type, :address, :city, :zip_code, :apn,
                    :owner_name, :owner_mailing, :assessed_value,
                    :contact_name, :contact_phone, :contact_email, :contact_role,
                    :extra_info, :filing_date, :doc_number, :case_number,
                    :amount_owed, :google_search_url, :first_seen, :last_seen,
                    :times_reported
                )""",
                {
                    "lead_hash": lead.get("lead_hash"),
                    "lead_type": lead.get("lead_type"),
                    "address": lead.get("address"),
                    "city": lead.get("city", "Palo Alto"),
                    "zip_code": lead.get("zip_code"),
                    "apn": lead.get("apn"),
                    "owner_name": lead.get("owner_name"),
                    "owner_mailing": lead.get("owner_mailing"),
                    "assessed_value": lead.get("assessed_value"),
                    "contact_name": lead.get("contact_name"),
                    "contact_phone": lead.get("contact_phone"),
                    "contact_email": lead.get("contact_email"),
                    "contact_role": lead.get("contact_role"),
                    "extra_info": lead.get("extra_info"),
                    "filing_date": lead.get("filing_date"),
                    "doc_number": lead.get("doc_number"),
                    "case_number": lead.get("case_number"),
                    "amount_owed": lead.get("amount_owed"),
                    "google_search_url": lead.get("google_search_url"),
                    "first_seen": lead.get("first_seen", ""),
                    "last_seen": lead.get("last_seen", ""),
                    "times_reported": lead.get("times_reported", 1),
                },
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                loaded += 1
        except sqlite3.Error as e:
            print(f"  Warning: could not insert lead {lead.get('lead_hash')}: {e}")
    return loaded


def load_runs(conn: sqlite3.Connection, runs: list) -> int:
    loaded = 0
    for run in runs:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO weekly_runs
                    (run_date, new_leads, total_leads, email_sent, notes)
                VALUES
                    (:run_date, :new_leads, :total_leads, :email_sent, :notes)""",
                {
                    "run_date": run.get("run_date"),
                    "new_leads": run.get("new_leads", 0),
                    "total_leads": run.get("total_leads", 0),
                    "email_sent": run.get("email_sent", 0),
                    "notes": run.get("notes"),
                },
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                loaded += 1
        except sqlite3.Error as e:
            print(f"  Warning: could not insert run {run.get('run_date')}: {e}")
    return loaded


def main():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)

    leads = []
    runs = []

    if os.path.exists(LEADS_JSON):
        with open(LEADS_JSON) as f:
            leads = json.load(f)
        print(f"Found {len(leads)} leads in {LEADS_JSON}")
    else:
        print(f"No leads JSON found at {LEADS_JSON} — starting with empty database")

    if os.path.exists(RUNS_JSON):
        with open(RUNS_JSON) as f:
            runs = json.load(f)
        print(f"Found {len(runs)} runs in {RUNS_JSON}")
    else:
        print(f"No runs JSON found at {RUNS_JSON}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    init_db(conn)

    loaded_leads = load_leads(conn, leads)
    loaded_runs = load_runs(conn, runs)

    conn.commit()
    conn.close()

    print(f"Loaded {loaded_leads} new leads, {loaded_runs} new runs into {DB_PATH}")


if __name__ == "__main__":
    main()
