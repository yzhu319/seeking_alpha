"""
db.py — local storage for Read Between Lines.

Everything lives in one SQLite file (rbl.db) next to this script, on this
laptop only:
  - companies   the tracked tickers (starting with the eCommerce sector)
  - filings     raw text + metadata for every 10-K / 10-Q / classic letter
                 we've fetched from SEC EDGAR, so we never re-fetch the same
                 document twice
  - ai_cache    AI outputs (TL;DR, breakdown, plain-English, highlights,
                 slides), cached per (filing, feature, model) so re-opening
                 a report doesn't re-spend API calls
  - settings    Gemini API key + model name, stored locally, nowhere else

No fees anywhere: SEC filings are free public documents, and this file is
the only place any of it is stored.
"""

import os
import json
import sqlite3
from datetime import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "rbl.db")

DEFAULT_SETTINGS = {
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "sec_contact_email": "",
}

# ---------------------------------------------------------------------------
# Seed data — the starting universe. Edit freely; anything fetched sticks
# around in `filings` regardless of whether it's still in this list.
# ---------------------------------------------------------------------------
SEED_COMPANIES = [
    ("AMZN", "Amazon.com", "eCommerce"),
    ("SHOP", "Shopify", "eCommerce"),
    ("WMT", "Walmart", "eCommerce"),
    ("CART", "Instacart (Maplebear)", "eCommerce"),
]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS companies ("
        "ticker TEXT PRIMARY KEY, name TEXT, sector TEXT, cik TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS filings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, form TEXT, title TEXT, "
        "period TEXT, filed_date TEXT, accession TEXT, source_url TEXT, "
        "raw_text TEXT, is_classic_letter INTEGER DEFAULT 0, letter_year TEXT, "
        "fetched_at TEXT)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_filing_source ON filings (ticker, source_url)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_cache ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, filing_id INTEGER, feature TEXT, "
        "model TEXT, content TEXT, created_at TEXT)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_cache ON ai_cache (filing_id, feature, model)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()

    if conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO companies (ticker, name, sector, cik) VALUES (?, ?, ?, NULL)",
            SEED_COMPANIES,
        )
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------
def get_companies():
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM companies ORDER BY ticker").fetchall()]
    conn.close()
    return rows


def upsert_company(ticker, name, sector, cik):
    conn = get_conn()
    conn.execute(
        "INSERT INTO companies (ticker, name, sector, cik) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(ticker) DO UPDATE SET name=excluded.name, sector=excluded.sector, cik=excluded.cik",
        (ticker.upper(), name, sector, cik),
    )
    conn.commit()
    conn.close()


def save_cik(ticker, cik):
    conn = get_conn()
    conn.execute("UPDATE companies SET cik=? WHERE ticker=?", (cik, ticker.upper()))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Filings
# ---------------------------------------------------------------------------
def get_filings(ticker, classic_only=False):
    conn = get_conn()
    q = "SELECT id, ticker, form, title, period, filed_date, accession, source_url, " \
        "is_classic_letter, letter_year, fetched_at FROM filings WHERE ticker=?"
    if classic_only:
        q += " AND is_classic_letter=1 ORDER BY letter_year DESC"
    else:
        # keep the Bezos letters out of the Read tab's filing list — they
        # have their own tab
        q += " AND is_classic_letter=0 ORDER BY filed_date DESC"
    rows = [dict(r) for r in conn.execute(q, (ticker.upper(),)).fetchall()]
    conn.close()
    return rows


def get_filing_text(filing_id):
    conn = get_conn()
    row = conn.execute("SELECT raw_text FROM filings WHERE id=?", (filing_id,)).fetchone()
    conn.close()
    return row["raw_text"] if row else ""


def filing_exists(ticker, source_url):
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM filings WHERE ticker=? AND source_url=?", (ticker.upper(), source_url)
    ).fetchone()
    conn.close()
    return row["id"] if row else None


def save_filing(ticker, form, title, period, filed_date, accession, source_url, raw_text,
                 is_classic_letter=False, letter_year=None):
    existing = filing_exists(ticker, source_url)
    if existing:
        return existing
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO filings (ticker, form, title, period, filed_date, accession, source_url, "
        "raw_text, is_classic_letter, letter_year, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ticker.upper(), form, title, period, filed_date, accession, source_url, raw_text,
         int(is_classic_letter), letter_year, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    fid = cur.lastrowid
    conn.close()
    return fid


# ---------------------------------------------------------------------------
# AI output cache
# ---------------------------------------------------------------------------
def get_ai_cache(filing_id, feature, model):
    conn = get_conn()
    row = conn.execute(
        "SELECT content FROM ai_cache WHERE filing_id=? AND feature=? AND model=?",
        (filing_id, feature, model),
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row["content"])
    except (TypeError, ValueError):
        return None


def set_ai_cache(filing_id, feature, model, content: dict):
    conn = get_conn()
    conn.execute(
        "INSERT INTO ai_cache (filing_id, feature, model, content, created_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(filing_id, feature, model) DO UPDATE SET content=excluded.content, created_at=excluded.created_at",
        (filing_id, feature, model, json.dumps(content), datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def clear_ai_cache():
    conn = get_conn()
    conn.execute("DELETE FROM ai_cache")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def get_settings():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    settings = dict(DEFAULT_SETTINGS)
    for r in rows:
        settings[r["key"]] = r["value"]
    return settings


def update_settings(updates: dict):
    conn = get_conn()
    for k, v in updates.items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (k, str(v)),
        )
    conn.commit()
    conn.close()
