"""
export_leads.py — Export SQLite leads database to JSON files for GitHub Pages hosting.

Reads data/leads.db and writes:
  docs/leads.json  — all lead rows as a JSON array
  docs/runs.json   — all weekly_run rows as a JSON array
"""
import json
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "leads.db")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
LEADS_JSON = os.path.join(DOCS_DIR, "leads.json")
RUNS_JSON = os.path.join(DOCS_DIR, "runs.json")


def export():
    os.makedirs(DOCS_DIR, exist_ok=True)

    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}. Writing empty JSON files.")
        with open(LEADS_JSON, "w") as f:
            json.dump([], f)
        with open(RUNS_JSON, "w") as f:
            json.dump([], f)
        print("Exported 0 leads, 0 runs")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    leads_rows = conn.execute(
        "SELECT * FROM leads ORDER BY first_seen DESC"
    ).fetchall()
    leads = [dict(row) for row in leads_rows]

    runs_rows = conn.execute(
        "SELECT * FROM weekly_runs ORDER BY run_date DESC"
    ).fetchall()
    runs = [dict(row) for row in runs_rows]

    conn.close()

    with open(LEADS_JSON, "w") as f:
        json.dump(leads, f, indent=2, default=str)

    with open(RUNS_JSON, "w") as f:
        json.dump(runs, f, indent=2, default=str)

    print(f"Exported {len(leads)} leads, {len(runs)} runs")
    print(f"  -> {LEADS_JSON}")
    print(f"  -> {RUNS_JSON}")


if __name__ == "__main__":
    export()
