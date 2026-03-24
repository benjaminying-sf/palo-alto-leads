"""
Flask web dashboard for the Palo Alto motivated-seller lead tracker.
Run:  python3 dashboard.py
Then open:  http://localhost:5050
"""
import json
import os
import sqlite3
from flask import Flask, jsonify, render_template, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "leads.db")

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))


# ── helpers ───────────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


# ── API routes ─────────────────────────────────────────────────────────────────

@app.route("/api/leads")
def api_leads():
    lead_type = request.args.get("type", "").strip()
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "first_seen").strip()

    # Whitelist sortable columns to prevent SQL injection
    allowed_sorts = {
        "first_seen", "last_seen", "filing_date", "owner_name",
        "address", "lead_type", "times_reported", "assessed_value",
    }
    if sort not in allowed_sorts:
        sort = "first_seen"

    params = []
    where_clauses = []

    if lead_type:
        where_clauses.append("lead_type = ?")
        params.append(lead_type)

    if q:
        where_clauses.append(
            "(owner_name LIKE ? OR address LIKE ? OR contact_name LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like])

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = f"SELECT * FROM leads {where_sql} ORDER BY {sort} DESC"

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    return jsonify(rows_to_dicts(rows))


@app.route("/api/stats")
def api_stats():
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

        type_counts = rows_to_dicts(
            conn.execute(
                "SELECT lead_type, COUNT(*) as count FROM leads GROUP BY lead_type"
            ).fetchall()
        )

        latest = conn.execute(
            "SELECT MAX(first_seen) as latest, MIN(first_seen) as earliest FROM leads"
        ).fetchone()

        run_count = conn.execute("SELECT COUNT(*) FROM weekly_runs").fetchone()[0]

    counts_by_type = {r["lead_type"]: r["count"] for r in type_counts}

    stats = {
        "total": total,
        "probate": counts_by_type.get("probate", 0),
        "foreclosure": counts_by_type.get("foreclosure", 0),
        "tax_default": counts_by_type.get("tax_default", 0),
        "divorce": counts_by_type.get("divorce", 0),
        "earliest": latest["earliest"] or "",
        "latest": latest["latest"] or "",
        "run_count": run_count,
    }
    return jsonify(stats)


# ── Main page ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    with get_connection() as conn:
        leads = rows_to_dicts(
            conn.execute("SELECT * FROM leads ORDER BY first_seen DESC").fetchall()
        )
        runs = rows_to_dicts(
            conn.execute(
                "SELECT * FROM weekly_runs ORDER BY run_date ASC"
            ).fetchall()
        )
        total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

        type_counts = rows_to_dicts(
            conn.execute(
                "SELECT lead_type, COUNT(*) as count FROM leads GROUP BY lead_type"
            ).fetchall()
        )
        latest_row = conn.execute(
            "SELECT MAX(first_seen) as latest, MIN(first_seen) as earliest FROM leads"
        ).fetchone()

    counts_by_type = {r["lead_type"]: r["count"] for r in type_counts}
    stats = {
        "total": total,
        "probate": counts_by_type.get("probate", 0),
        "foreclosure": counts_by_type.get("foreclosure", 0),
        "tax_default": counts_by_type.get("tax_default", 0),
        "divorce": counts_by_type.get("divorce", 0),
        "earliest": (latest_row["earliest"] or "")[:10],
        "latest": (latest_row["latest"] or "")[:10],
    }

    return render_template(
        "dashboard.html",
        leads=leads,
        runs=runs,
        stats=stats,
        leads_json=json.dumps(leads),
        runs_json=json.dumps(runs),
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Dashboard running at http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False)
