"""
common.py — shared logic for AI Infra Watch.

Everything that isn't screen-drawing lives here: the local database, the
breakout math, fetching prices, sending alerts, and turning the OS's own
scheduler on/off. app.py (the dashboard) and scanner.py (the background
checker) both import this, so the two are always looking at the exact same
watchlist, thresholds, and history — edit something in the app, the
background checker picks it up on its next run automatically.

Data lives in ai_infra.db, a single file next to this script, on this
laptop only. Nothing here calls out to any cloud service.
"""

import os
import sys
import sqlite3
import smtplib
import platform
import subprocess
from datetime import datetime
from email.message import EmailMessage

import pandas as pd
import yfinance as yf

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "ai_infra.db")

TASK_NAME = "AIInfraWatchScan"
CRON_MARKER = "# ai-infra-watch-autogen"

# ---------------------------------------------------------------------------
# Seed data — only used the very first time the app runs, to populate the
# database. After that, the database is the source of truth; edit the
# watchlist from the Watchlist tab, not by editing this file.
# ---------------------------------------------------------------------------
DEFAULT_WATCHLIST = [
    ("NVDA", "Nvidia", "Compute"),
    ("AMD", "AMD", "Compute"),
    ("AVGO", "Broadcom", "Networking/ASIC"),
    ("TSM", "Taiwan Semiconductor", "Foundry"),
    ("INTC", "Intel", "Foundry"),
    ("QCOM", "Qualcomm", "Compute"),
    ("MRVL", "Marvell", "Networking/ASIC"),
    ("ARM", "Arm Holdings", "Compute"),
    ("MU", "Micron", "Memory"),
    ("STX", "Seagate", "Storage"),
    ("WDC", "Western Digital", "Storage"),
    ("SNDK", "SanDisk", "Storage"),
    ("AMAT", "Applied Materials", "Equipment"),
    ("LRCX", "Lam Research", "Equipment"),
    ("KLAC", "KLA Corp", "Equipment"),
    ("ASML", "ASML Holding", "Equipment"),
    ("ANET", "Arista Networks", "Networking"),
    ("CIEN", "Ciena", "Networking"),
    ("NOK", "Nokia", "Networking"),
    ("VRT", "Vertiv", "Cooling"),
    ("MOD", "Modine", "Cooling"),
    ("ETN", "Eaton", "Electrical"),
    ("NVT", "nVent Electric", "Electrical"),
    ("CEG", "Constellation Energy", "Power"),
    ("VST", "Vistra", "Power"),
    ("NRG", "NRG Energy", "Power"),
    ("EQIX", "Equinix", "Data-center REIT"),
    ("DLR", "Digital Realty", "Data-center REIT"),
    ("SMCI", "Super Micro Computer", "Servers"),
    ("DELL", "Dell Technologies", "Servers"),
]

DEFAULT_SETTINGS = {
    "lookback_high": 60,
    "vol_window": 20,
    "sma_fast": 20,
    "sma_slow": 50,
    "vol_mult": 1.3,
    "cooldown": 10,
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_pass": "",
    "alert_to": "",
    "scan_interval_hours": 2,
}

INT_KEYS = {"lookback_high", "vol_window", "sma_fast", "sma_slow", "cooldown", "smtp_port", "scan_interval_hours"}
FLOAT_KEYS = {"vol_mult"}

CARRIER_GATEWAYS = {
    "AT&T": "txt.att.net",
    "T-Mobile": "tmomail.net",
    "Verizon": "vtext.com",
    "Sprint": "messaging.sprintpcs.com",
}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS watchlist ("
        "symbol TEXT PRIMARY KEY, name TEXT, sector TEXT, enabled INTEGER DEFAULT 1)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS signal_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, run_date TEXT, symbol TEXT, sector TEXT, "
        "price_date TEXT, close REAL, fired INTEGER)"
    )
    conn.commit()

    if conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO watchlist (symbol, name, sector, enabled) VALUES (?, ?, ?, 1)",
            DEFAULT_WATCHLIST,
        )
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit()
    conn.close()


def get_watchlist(enabled_only=False):
    conn = get_conn()
    q = "SELECT symbol, name, sector, enabled FROM watchlist"
    if enabled_only:
        q += " WHERE enabled=1"
    q += " ORDER BY sector, symbol"
    rows = [dict(r) for r in conn.execute(q).fetchall()]
    conn.close()
    return rows


def save_watchlist(rows):
    """Replace the whole watchlist table with the given rows (from the editor)."""
    conn = get_conn()
    conn.execute("DELETE FROM watchlist")
    clean = [
        (str(r["symbol"]).upper().strip(), r.get("name") or "", r.get("sector") or "", int(bool(r.get("enabled", True))))
        for r in rows
        if r.get("symbol")
    ]
    conn.executemany("INSERT OR REPLACE INTO watchlist (symbol, name, sector, enabled) VALUES (?, ?, ?, ?)", clean)
    conn.commit()
    conn.close()


def get_settings():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    settings = dict(DEFAULT_SETTINGS)
    for r in rows:
        settings[r["key"]] = r["value"]
    for k in INT_KEYS:
        try:
            settings[k] = int(float(settings[k]))
        except (ValueError, TypeError):
            pass
    for k in FLOAT_KEYS:
        try:
            settings[k] = float(settings[k])
        except (ValueError, TypeError):
            pass
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


# ---------------------------------------------------------------------------
# Signal math — a Donchian breakout, confirmed by volume, filtered to an
# established uptrend. Identical definition everywhere it's used.
# ---------------------------------------------------------------------------
def compute_signals(df: pd.DataFrame, settings: dict) -> pd.DataFrame:
    df = df.copy()
    lb, vw = int(settings["lookback_high"]), int(settings["vol_window"])
    sf, ss = int(settings["sma_fast"]), int(settings["sma_slow"])
    vm, cd = float(settings["vol_mult"]), int(settings["cooldown"])

    df["donchian_high"] = df["High"].rolling(lb).max().shift(1)
    df["vol_avg"] = df["Volume"].rolling(vw).mean().shift(1)
    df["sma_fast"] = df["Close"].rolling(sf).mean()
    df["sma_slow"] = df["Close"].rolling(ss).mean()

    candidate = (
        (df["Close"] > df["donchian_high"])
        & (df["Volume"] > vm * df["vol_avg"])
        & (df["sma_fast"] > df["sma_slow"])
    ).fillna(False)

    fired = pd.Series(False, index=df.index)
    last_fire = -10**9
    for i, is_candidate in enumerate(candidate):
        if is_candidate and (i - last_fire) > cd:
            fired.iloc[i] = True
            last_fire = i
    df["fired"] = fired
    return df


def fetch_price_data(symbols, period="2y"):
    if not symbols:
        return {}
    raw = yf.download(
        tickers=" ".join(symbols), period=period, interval="1d",
        group_by="ticker", auto_adjust=True, threads=True, progress=False,
    )
    out = {}
    for sym in symbols:
        try:
            df = raw[sym] if len(symbols) > 1 else raw
            df = df.dropna(subset=["Close", "Volume"])
            if not df.empty:
                out[sym] = df
        except Exception:
            continue
    return out


def analyze_watchlist(watchlist, settings):
    """Fetch + compute signals for every enabled ticker. Returns {symbol: df}."""
    symbols = [w["symbol"] for w in watchlist]
    raw = fetch_price_data(symbols)
    results = {}
    min_len = int(settings["lookback_high"]) + int(settings["sma_slow"])
    for w in watchlist:
        sym = w["symbol"]
        df = raw.get(sym)
        if df is None or len(df) < min_len:
            continue
        results[sym] = compute_signals(df, settings)
    return results


def get_fresh_signals(results, watchlist):
    """Names whose most recent bar is a fresh fire."""
    meta = {w["symbol"]: w for w in watchlist}
    fresh = []
    for sym, df in results.items():
        last = df.iloc[-1]
        if bool(last["fired"]):
            fresh.append(
                {
                    "symbol": sym,
                    "name": meta.get(sym, {}).get("name", sym),
                    "sector": meta.get(sym, {}).get("sector", ""),
                    "date": df.index[-1].date().isoformat(),
                    "close": float(last["Close"]),
                }
            )
    return fresh


def log_results(results, watchlist):
    meta = {w["symbol"]: w for w in watchlist}
    run_date = datetime.now().date().isoformat()
    rows = []
    for sym, df in results.items():
        last = df.iloc[-1]
        rows.append(
            (run_date, sym, meta.get(sym, {}).get("sector", ""), df.index[-1].date().isoformat(),
             float(last["Close"]), int(bool(last["fired"])))
        )
    if not rows:
        return
    conn = get_conn()
    conn.executemany(
        "INSERT INTO signal_log (run_date, symbol, sector, price_date, close, fired) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
def send_alert(fresh_signals, settings):
    host, user, password = settings.get("smtp_host"), settings.get("smtp_user"), settings.get("smtp_pass")
    port = int(settings.get("smtp_port", 587) or 587)
    recipients = [r.strip() for r in str(settings.get("alert_to", "")).split(",") if r.strip()]

    if not all([host, user, password]) or not recipients:
        return False, "Email isn't configured yet — fill in the Alerts tab first."

    lines = [
        f"{s['symbol']} ({s['sector']}) — breakout confirmed {s['date']}, close ${s['close']:.2f}"
        for s in fresh_signals
    ]
    body = (
        "AI Infra Watch — new breakout signal(s):\n\n"
        + "\n".join(lines)
        + "\n\nRules: new high, on above-average volume, inside an established uptrend."
        + "\nMechanical screen only — not investment advice, do your own research.\n"
    )
    msg = EmailMessage()
    msg["Subject"] = f"AI Infra Watch: {len(fresh_signals)} new signal(s)"
    msg["From"] = user
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        return True, f"Sent to {len(recipients)} recipient(s)."
    except Exception as e:
        return False, f"Couldn't send: {e}"


# ---------------------------------------------------------------------------
# Background scheduling — registers scanner.py with the OS's own scheduler
# (cron on macOS/Linux, Task Scheduler on Windows) so alerts keep flowing
# even when the dashboard isn't open. Best-effort: if it can't set itself up
# (permissions, etc.) the README has the two-line manual fallback.
# ---------------------------------------------------------------------------
def _scanner_path():
    return os.path.join(APP_DIR, "scanner.py")


def scheduler_status():
    try:
        if platform.system() == "Windows":
            r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True, text=True)
            return r.returncode == 0
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return CRON_MARKER in (r.stdout or "")
    except FileNotFoundError:
        return False


def enable_scheduler(interval_hours: int):
    python_exe, script = sys.executable, _scanner_path()
    if platform.system() == "Windows":
        minutes = max(1, int(interval_hours * 60))
        subprocess.run(
            ["schtasks", "/Create", "/SC", "MINUTE", "/MO", str(minutes),
             "/TN", TASK_NAME, "/TR", f'"{python_exe}" "{script}"', "/F"],
            check=True, capture_output=True, text=True,
        )
    else:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout or ""
        lines = [l for l in existing.splitlines() if CRON_MARKER not in l]
        step = max(1, int(interval_hours))
        lines.append(f"0 */{step} * * 1-5 {python_exe} {script} >> {APP_DIR}/scanner.log 2>&1 {CRON_MARKER}")
        subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)


def disable_scheduler():
    if platform.system() == "Windows":
        subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True)
    else:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout or ""
        lines = [l for l in existing.splitlines() if CRON_MARKER not in l]
        subprocess.run(["crontab", "-"], input="\n".join(lines) + ("\n" if lines else ""), text=True, check=True)
