"""
early.py — the Early Radar: find the *next* MU/SNDK/WDC weeks-to-months
before the crowd, while the discussion is still a few hundred smart people.

Wave Radar (ideas.py) detects waves that already have price confirmation —
by design it is late. This module scores the signals that historically
*preceded* price in the EV, AI, and memory booms, all from free public data:

  1. Chatter trajectory — mention growth on Reddit from a LOW base. Rank #150
     climbing to #60 on sustained multi-day growth is the early crowd; rank #1
     is CNBC. (ApeWisdom now; gets sharper over time as mention_log
     accumulates daily snapshots and real weekly slopes become computable.)
  2. Institutional recognition — analysts quietly revising estimates UP.
     Up-revision breadth and estimate drift famously lead the full repricing
     (post-earnings-announcement drift). Free via Yahoo Finance.
  3. Ecosystem validation — how often ALL SEC filings (customers, suppliers,
     competitors — not just the company itself) mention the name vs a year
     ago. "High bandwidth memory" filings ran 28 → 99/quarter before memory
     stocks finished repricing. Free via EDGAR full-text search.

Then an EARLINESS GATE: if the stock already ran hard, it's Wave Radar
territory and the score is damped — this list is specifically for names the
price hasn't fully voted on yet.

X/Twitter and Bloomberg are paywalled; Reddit chatter, analyst revisions,
and EDGAR filings are the free windows into the same three crowds (retail,
sell-side, corporate). Mechanical screen only — not investment advice.
"""

import re
import time
from datetime import datetime

import requests
import pandas as pd

import common
import ideas as idea_engine

EDGAR_FTS = "https://efts.sec.gov/LATEST/search-index"
EDGAR_HEADERS = {"User-Agent": "WaveRadar research contact@example.com"}

SHORTLIST_SIZE = 15   # names that get the slow (revisions + EDGAR) pass
CANDIDATE_MAX_RANK = 300  # Reddit rank cutoff for names outside the universe

_NAME_NOISE = re.compile(
    r"\b(incorporated|inc|corporation|corp|company|co|ltd|plc|holdings?|group|"
    r"platforms?|technologies|technology|adr)\b\.?,?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Mention history — a daily snapshot of the whole ApeWisdom board, so the
# trajectory math gets better every day the scanner runs.
# ---------------------------------------------------------------------------
def _ensure_tables():
    """Create this module's tables directly — survives partial hot-reloads
    (e.g. Streamlit Cloud reloading app.py but keeping an older common.py)."""
    conn = common.get_conn()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS mention_log ("
        "snap_date TEXT, ticker TEXT, mentions INTEGER, rank INTEGER, upvotes INTEGER, "
        "PRIMARY KEY (snap_date, ticker))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS early_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, run_date TEXT, symbol TEXT, theme TEXT, "
        "early_score INTEGER, chatter INTEGER, revisions INTEGER, filings INTEGER, "
        "ret_3m REAL, badge TEXT, close REAL, why TEXT)"
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_early_day ON early_log (run_date, symbol)")
    conn.commit()
    conn.close()


def snapshot_mentions(sentiment):
    if not sentiment:
        return
    today = datetime.now().date().isoformat()
    conn = common.get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO mention_log (snap_date, ticker, mentions, rank, upvotes) VALUES (?, ?, ?, ?, ?)",
        [(today, sym, s["mentions"], s["rank"], s["upvotes"]) for sym, s in sentiment.items()],
    )
    conn.commit()
    conn.close()


def mention_history(days=35):
    """{ticker: [(snap_date, mentions), ...] oldest-first} from stored snapshots."""
    conn = common.get_conn()
    rows = conn.execute(
        "SELECT snap_date, ticker, mentions FROM mention_log "
        "WHERE snap_date >= date('now', ?) ORDER BY snap_date",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    hist = {}
    for r in rows:
        hist.setdefault(r["ticker"], []).append((r["snap_date"], r["mentions"]))
    return hist


# ---------------------------------------------------------------------------
# Ingredient 1 — chatter trajectory (early crowd, not arrived crowd)
# ---------------------------------------------------------------------------
def chatter_score(sym, sent, hist):
    s = sent.get(sym)
    if not s:
        return 0, ""
    rank, mentions, prev = s["rank"], s["mentions"], s["mentions_24h_ago"]

    # Under-the-radar sweet spot: talked about, but not yet everywhere.
    level = 20.0 if 20 <= rank <= 400 else (8.0 if rank < 20 else 0.0)

    # Trajectory: prefer a real multi-day slope from our own snapshots;
    # fall back to ApeWisdom's 24h delta until history accumulates.
    series = hist.get(sym, [])
    window = "24h"
    if len(series) >= 6:
        vals = [m for _, m in series]
        recent = sum(vals[-3:]) / 3
        base = sum(vals[-9:-3]) / max(1, len(vals[-9:-3]))
        ratio = recent / base if base > 0 else (2.0 if recent >= 15 else 1.0)
        window = f"{min(len(series), 9)}d"
    else:
        ratio = mentions / prev if prev > 0 else (2.0 if mentions >= 15 else 1.0)

    if ratio >= 3:
        traj = 45.0
    elif ratio >= 1.2:
        traj = (ratio - 1.2) / 1.8 * 45
    else:
        traj = 0.0
    traj *= min(1.0, mentions / 15)  # tiny-count growth is noise

    # Climbing the board: rank 200 → 100 is the early crowd gathering.
    climb = 0.0
    rank_prev = s.get("rank_24h_ago")
    if rank_prev and rank_prev > rank:
        climb = min(20.0, (rank_prev - rank) / rank * 40)

    persistence = 15.0 if (mentions >= 10 and prev >= 10) else 0.0

    score = round(min(100, level + traj + climb + persistence))
    why = f"Reddit rank #{rank}, {mentions} mentions ({ratio:.1f}x over {window})"
    if climb > 5 and rank_prev:
        why += f", climbed from #{rank_prev} yesterday"
    return score, why


# ---------------------------------------------------------------------------
# Ingredient 2 — analysts quietly revising up (Yahoo Finance)
# ---------------------------------------------------------------------------
def fetch_revisions(sym):
    import yfinance as yf

    out = {"up30": None, "down30": None, "trend_chg": None, "name": None}
    try:
        t = yf.Ticker(sym)
        rev = t.eps_revisions
        if rev is not None and not rev.empty:
            rows = [r for r in ("0q", "0y") if r in rev.index]
            out["up30"] = int(sum(rev.loc[r, "upLast30days"] or 0 for r in rows))
            out["down30"] = int(sum(rev.loc[r, "downLast30days"] or 0 for r in rows))
        trend = t.eps_trend
        if trend is not None and not trend.empty and "0y" in trend.index:
            cur, old = trend.loc["0y", "current"], trend.loc["0y", "90daysAgo"]
            if cur and old and abs(old) > 1e-9:
                out["trend_chg"] = float(cur) / float(old) - 1
        try:
            out["name"] = t.info.get("shortName")
        except Exception:
            pass
    except Exception:
        pass
    return out


def revisions_score(rev):
    score, bits = 0.0, []
    up, down, chg = rev.get("up30"), rev.get("down30"), rev.get("trend_chg")
    if up is not None:
        if up >= 4 and (down or 0) == 0:
            score += 40
        elif up > (down or 0):
            score += 25
        elif up > 0:
            score += 10
        if (down or 0) > up:
            score -= 20  # analysts net-cutting — estimate drift alone doesn't earn points
        bits.append(f"{up} up / {down or 0} down revisions (30d)")
    if chg is not None:
        if chg >= 0.25:
            score += 60
        elif chg >= 0.10:
            score += 40
        elif chg >= 0.05:
            score += 25
        elif chg > 0.01:
            score += 10
        bits.append(f"FY estimate {chg:+.0%} in 90d")
    return round(min(100, max(0, score))), ", ".join(bits) if bits else "no analyst coverage data"


# ---------------------------------------------------------------------------
# Ingredient 3 — the ecosystem starts putting the name in its filings (EDGAR)
# ---------------------------------------------------------------------------
# Operational filings only — a mention in an 8-K/10-K is a real business
# relationship (customer, supplier, competitor, partner). Without this filter
# mega-caps drown in thousands of fund-holdings filings and the ratio ≈ 1.
EDGAR_FORMS = "8-K,10-K,10-Q,6-K,20-F,S-1"


def _edgar_count(query, start, end, attempts=2):
    last_err = None
    for i in range(attempts):
        try:
            r = requests.get(
                EDGAR_FTS,
                params={"q": f'"{query}"', "forms": EDGAR_FORMS, "startdt": start, "enddt": end},
                headers=EDGAR_HEADERS, timeout=15,
            )
            r.raise_for_status()
            return int(r.json()["hits"]["total"]["value"])
        except Exception as e:  # EDGAR throttles bursts; back off and retry once
            last_err = e
            time.sleep(1.0 + i)
    raise last_err


def clean_company_name(name):
    """'Micron Technology, Inc.' → 'Micron Technology' → usable FTS phrase."""
    if not name:
        return None
    base = _NAME_NOISE.sub("", re.sub(r"\(.*?\)", "", name)).strip(" .,&-")
    base = re.sub(r"\s+", " ", base)
    return base if len(base) >= 4 else None


def filings_velocity(name):
    """(recent_90d, year_ago_90d) filing counts mentioning the company, or None."""
    phrase = clean_company_name(name)
    if not phrase:
        return None
    today = pd.Timestamp.now()
    try:
        recent = _edgar_count(phrase, (today - pd.Timedelta(days=90)).date().isoformat(),
                              today.date().isoformat())
        time.sleep(0.5)  # EDGAR politeness
        yearago = _edgar_count(phrase, (today - pd.Timedelta(days=455)).date().isoformat(),
                               (today - pd.Timedelta(days=365)).date().isoformat())
        time.sleep(0.5)
        return recent, yearago
    except Exception:
        return None


def filings_score(velocity):
    if velocity is None:
        return 0, "no filings data"
    recent, yearago = velocity
    ratio = recent / max(1, yearago)
    if ratio >= 3:
        score = 100.0
    elif ratio >= 2:
        score = 70.0
    elif ratio >= 1.5:
        score = 45.0
    elif ratio >= 1.2:
        score = 20.0
    else:
        score = 0.0
    if recent < 8:
        score *= 0.5  # too few filings to trust the ratio
    return round(score), f"SEC filings mentioning it: {yearago} → {recent} per 90d ({ratio:.1f}x YoY)"


# ---------------------------------------------------------------------------
# Earliness gate — this list is for names price hasn't fully voted on yet
# ---------------------------------------------------------------------------
def earliness(ret_3m):
    if ret_3m is None:
        return 0.9, "❔ no price history"
    if ret_3m > 0.75:
        return 0.55, "🌊 already running — Wave Radar territory"
    if ret_3m > 0.30:
        return 0.85, "🏃 moving, but not done repricing"
    if ret_3m >= -0.20:
        return 1.0, "🌱 pre-wave window"
    return 0.7, "🔻 falling — chatter may be bagholders, not scouts"


WEIGHTS = {"chatter": 0.35, "revisions": 0.35, "filings": 0.30}


def generate_early(sentiment, price_data, settings):
    """
    Returns a ranked list of early-detection candidates with full explanations.
    price_data: {sym: df} — used only for the earliness gate; symbols missing
    from it get fetched in one small batch.
    """
    _ensure_tables()
    snapshot_mentions(sentiment)  # today's brick in the trajectory wall
    hist = mention_history()
    uni = idea_engine.universe()

    # Outside-universe names must show SUSTAINED chatter (today and yesterday),
    # not a one-day news pop — one-day spikes are reactions, multi-day growth
    # is a narrative forming. This one gate removes most acronym-collision
    # noise (CD, HBM-the-ticker, crypto spillover) without any blocklist.
    candidates = set(uni)
    for sym, s in sentiment.items():
        if (
            s["rank"] <= CANDIDATE_MAX_RANK
            and sym not in idea_engine._NOT_A_COMPANY
            and not idea_engine.looks_like_fund(s["name"])
            and (sym in uni or (s["mentions"] >= 10 and s["mentions_24h_ago"] >= 8))
        ):
            candidates.add(sym)

    pre = []
    for sym in candidates:
        c_score, c_why = chatter_score(sym, sentiment, hist)
        if c_score > 0:
            pre.append((sym, c_score, c_why))
    pre.sort(key=lambda x: x[1], reverse=True)
    shortlist = pre[:SHORTLIST_SIZE]

    # 3-month returns for the gate — one extra batched download for outsiders.
    missing = [sym for sym, _, _ in shortlist if sym not in price_data]
    extra = common.fetch_price_data(missing, period="6mo") if missing else {}

    # Hard budget for the slow EDGAR pass: when the SEC throttles or errors,
    # degrade to "no filings data" instead of hanging the whole page.
    filings_deadline = time.time() + 90

    out = []
    for sym, c_score, c_why in shortlist:
        df = price_data.get(sym) if sym in price_data else extra.get(sym)
        ret_3m = None
        if df is not None and len(df) >= 64:
            ret_3m = float(df["Close"].iloc[-1] / df["Close"].iloc[-63] - 1)
        gate, badge = earliness(ret_3m)

        rev = fetch_revisions(sym)
        r_score, r_why = revisions_score(rev)
        name = rev.get("name") or sentiment.get(sym, {}).get("name", sym)
        velocity = filings_velocity(name) if time.time() < filings_deadline else None
        f_score, f_why = filings_score(velocity)

        raw = (c_score * WEIGHTS["chatter"] + r_score * WEIGHTS["revisions"]
               + f_score * WEIGHTS["filings"])
        out.append({
            "symbol": sym,
            "name": name,
            "theme": uni.get(sym, "outside universe"),
            "early_score": round(raw * gate),
            "chatter": c_score,
            "revisions": r_score,
            "filings": f_score,
            "ret_3m": ret_3m,
            "badge": badge,
            "close": float(df["Close"].iloc[-1]) if df is not None and len(df) else None,
            "why": " · ".join([c_why, r_why, f_why]),
        })
    out.sort(key=lambda x: x["early_score"], reverse=True)
    return out
