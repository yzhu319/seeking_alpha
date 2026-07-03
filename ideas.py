"""
ideas.py — the idea engine: turns raw data into ranked, explained ideas.

First-principles model of the big waves this app is built to catch
(EV/Tesla 2020, AI/Nvidia 2023, AI-infra/memory 2025): every one of them
showed the same three ingredients at once, visible well before the move was
over —

  1. Price wave      — the stock is already outperforming, making new highs
                       on volume. The market has started to vote.
  2. Crowd ignition  — retail chatter (Reddit etc.) accelerating. Narrative
                       spreading = fuel remaining.
  3. Fundamental thrust — revenue/earnings actually inflecting, so it's a
                       business wave, not just a story.

Each ingredient is scored 0-100 from transparent rules below, then blended
into one Wave Score. Nothing here predicts; it *detects* waves that are
already forming, early enough that a 2-5x tail can still matter.

Mechanical screen only — not investment advice.
"""

import requests
import pandas as pd

import common

# ---------------------------------------------------------------------------
# The universe — thematic baskets of where big technology/consumer waves
# plausibly come from. Edit freely; the scoring is universe-agnostic.
# The AI-infra basket from the original app lives on as one theme here.
# ---------------------------------------------------------------------------
THEMES = {
    "AI Infrastructure": [
        "NVDA", "AMD", "AVGO", "TSM", "INTC", "QCOM", "MRVL", "ARM", "MU",
        "STX", "WDC", "SNDK", "AMAT", "LRCX", "KLAC", "ASML", "ANET", "CIEN",
        "VRT", "MOD", "ETN", "NVT", "EQIX", "DLR", "SMCI", "DELL",
    ],
    "AI Software & Platforms": [
        "MSFT", "GOOGL", "META", "AMZN", "AAPL", "PLTR", "NOW", "CRM", "ORCL",
        "SNOW", "DDOG", "APP", "DUOL", "RDDT",
    ],
    "Power & Grid": ["CEG", "VST", "NRG", "TLN", "GEV", "PWR"],
    "Nuclear Renaissance": ["OKLO", "SMR", "CCJ", "LEU", "BWXT", "UEC"],
    "EV & Autonomy": ["TSLA", "RIVN", "NIO", "XPEV", "LI", "BYDDY", "MBLY", "QS"],
    "Robotics & Automation": ["ISRG", "ROK", "TER", "SYM", "PATH", "FANUY"],
    "Crypto Rails": ["COIN", "HOOD", "MSTR", "MARA", "RIOT", "CLSK"],
    "Biotech & GLP-1": ["LLY", "NVO", "VKTX", "AMGN", "REGN", "CRSP", "NTLA"],
    "Space & Defense Tech": ["RKLB", "ASTS", "PL", "LUNR", "AVAV", "KTOS"],
    "Quantum": ["IONQ", "RGTI", "QBTS"],
    "Cybersecurity": ["CRWD", "PANW", "ZS", "FTNT", "S", "NET"],
    "Consumer Internet": ["SHOP", "MELI", "SE", "DASH", "UBER", "ABNB", "NFLX", "SPOT"],
}

# ETF/fund/crypto tickers to ignore when Reddit surfaces "new" names
_NOT_A_COMPANY = {
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "VT", "VTV", "VUG", "VGT", "VYM",
    "VXUS", "VXF", "SPMO", "SCHD", "JEPI", "JEPQ", "TQQQ", "SQQQ", "SOXL", "SOXS",
    "UVXY", "VXX", "GLD", "SLV", "TLT", "HYG", "ARKK", "SMH", "XLK", "XLE", "XLF",
    "XLV", "IBIT", "FBTC", "GBTC", "ETHA",
    "BTC", "ETH", "DOGE", "LINK", "XRP", "ADA", "SOL", "HODL",
}

_FUND_NAME_WORDS = ("etf", "fund", "trust", "shares", "index", "bitcoin", "ethereum")


def looks_like_fund(name):
    """Name-based catch-all for ETFs/funds the ticker blocklist misses."""
    low = (name or "").lower()
    return any(w in low for w in _FUND_NAME_WORDS)

APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}"


def universe():
    """{symbol: theme} for every ticker across all themes (first theme wins)."""
    out = {}
    for theme, syms in THEMES.items():
        for s in syms:
            out.setdefault(s, theme)
    return out


# ---------------------------------------------------------------------------
# Ingredient 2 — crowd ignition (Reddit mentions via the free ApeWisdom API)
# ---------------------------------------------------------------------------
def fetch_sentiment(pages=3):
    """
    {ticker: {mentions, mentions_24h_ago, rank, upvotes, name}} for the
    ~100*pages most-discussed tickers across investing subreddits right now.
    Returns {} on any failure — sentiment is then simply scored 0.
    """
    out = {}
    for page in range(1, pages + 1):
        try:
            r = requests.get(APEWISDOM_URL.format(page=page), timeout=15)
            r.raise_for_status()
            for row in r.json().get("results", []):
                out[row["ticker"]] = {
                    "mentions": int(row.get("mentions") or 0),
                    "mentions_24h_ago": int(row.get("mentions_24h_ago") or 0),
                    "rank": int(row.get("rank") or 999),
                    "rank_24h_ago": int(row.get("rank_24h_ago") or 0) or None,
                    "upvotes": int(row.get("upvotes") or 0),
                    "name": row.get("name") or row["ticker"],
                }
        except Exception:
            break
    return out


def sentiment_score(sym, sent):
    """0-100. Level of chatter (are people talking?) + acceleration (is it spreading?)."""
    s = sent.get(sym)
    if not s:
        return 0, ""
    level = max(0.0, 50 - (s["rank"] - 1) * 50 / 300)  # rank 1 → 50 pts, fades to 0 by rank ~300
    prev = s["mentions_24h_ago"]
    growth_ratio = s["mentions"] / prev if prev > 0 else (2.0 if s["mentions"] >= 20 else 1.0)
    if growth_ratio >= 3:
        accel = 50.0
    elif growth_ratio >= 1:
        accel = (growth_ratio - 1) * 25  # 2x day-over-day → 25 pts
    else:
        accel = 0.0
    accel *= min(1.0, s["mentions"] / 20)  # 6 mentions tripling is noise, 60 tripling is ignition
    why = f"Reddit rank #{s['rank']} ({s['mentions']} mentions"
    why += f", {growth_ratio:.1f}x vs yesterday)" if prev > 0 else ")"
    return round(min(100, level + accel)), why


# ---------------------------------------------------------------------------
# Ingredient 1 — the price wave
# ---------------------------------------------------------------------------
def momentum_metrics(price_data):
    """Per-symbol return/trend stats from the daily price frames."""
    rows = {}
    for sym, df in price_data.items():
        close = df["Close"]
        if len(close) < 130:
            continue
        rows[sym] = {
            "ret_3m": close.iloc[-1] / close.iloc[-63] - 1,
            "ret_6m": close.iloc[-1] / close.iloc[-126] - 1,
            "above_200sma": bool(close.iloc[-1] > close.rolling(200).mean().iloc[-1])
            if len(close) >= 200 else bool(close.iloc[-1] > close.mean()),
            "pct_off_high": close.iloc[-1] / close.max() - 1,
            "last_close": float(close.iloc[-1]),
        }
    return rows


def momentum_score(sym, mom, all_mom, breakout_recent):
    """0-100. Relative strength within the universe + trend + fresh breakout."""
    m = mom.get(sym)
    if not m:
        return 0, ""
    r3 = pd.Series({s: v["ret_3m"] for s, v in all_mom.items()}).rank(pct=True)[sym]
    r6 = pd.Series({s: v["ret_6m"] for s, v in all_mom.items()}).rank(pct=True)[sym]
    score = r3 * 35 + r6 * 25
    if m["above_200sma"]:
        score += 15
    if m["pct_off_high"] > -0.05:
        score += 10
    if breakout_recent:
        score += 15
    why = f"3-mo {m['ret_3m']:+.0%} (top {max(1, 100 - int(r3 * 100))}% of universe), 6-mo {m['ret_6m']:+.0%}"
    if breakout_recent:
        why += ", fresh volume breakout"
    return round(min(100, score)), why


# ---------------------------------------------------------------------------
# Ingredient 3 — fundamental thrust (yfinance company info; ~1 request per
# ticker, so only fetched for the shortlist that already shows wave+crowd)
# ---------------------------------------------------------------------------
def fetch_fundamentals(symbols):
    import yfinance as yf

    out = {}
    for sym in symbols:
        try:
            info = yf.Ticker(sym).info
            out[sym] = {
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "gross_margins": info.get("grossMargins"),
                "forward_pe": info.get("forwardPE"),
                "market_cap": info.get("marketCap"),
                "name": info.get("shortName") or sym,
            }
        except Exception:
            out[sym] = {}
    return out


def fundamental_score(sym, fund):
    """0-100. Is the business itself inflecting, or is this only a story?"""
    f = fund.get(sym) or {}
    score, bits = 0, []
    rg, eg, gm = f.get("revenue_growth"), f.get("earnings_growth"), f.get("gross_margins")
    if rg is not None:
        if rg >= 0.50:
            score += 45
        elif rg >= 0.25:
            score += 30
        elif rg >= 0.10:
            score += 15
        bits.append(f"revenue {rg:+.0%} YoY")
    if eg is not None:
        if eg >= 0.50:
            score += 35
        elif eg >= 0.25:
            score += 22
        elif eg > 0:
            score += 10
        bits.append(f"earnings {eg:+.0%} YoY")
    if gm is not None and gm >= 0.50:
        score += 20
        bits.append(f"{gm:.0%} gross margin")
    return min(100, score), ", ".join(bits) if bits else "no fundamentals data"


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------
WEIGHTS = {"momentum": 0.40, "sentiment": 0.25, "fundamentals": 0.35}
SHORTLIST_SIZE = 25  # how many pre-ranked names get the (slow) fundamentals pass


def generate_ideas(price_data, signal_results, settings, sentiment=None):
    """
    The main entry point. Returns (ideas, sentiment) where ideas is a list of
    dicts sorted by wave score, each fully explained.

    price_data:     {sym: OHLCV df} for the whole universe
    signal_results: {sym: df-with-'fired'} from common.analyze (for breakout recency)
    """
    uni = universe()
    sent = sentiment if sentiment is not None else fetch_sentiment()
    mom = momentum_metrics(price_data)

    pre = []
    for sym in mom:
        fired_recent = False
        sdf = signal_results.get(sym)
        if sdf is not None and len(sdf) >= 10:
            fired_recent = bool(sdf["fired"].iloc[-10:].any())
        m_score, m_why = momentum_score(sym, mom, mom, fired_recent)
        s_score, s_why = sentiment_score(sym, sent)
        pre.append({"symbol": sym, "momentum": m_score, "m_why": m_why,
                    "sentiment": s_score, "s_why": s_why})

    pre.sort(key=lambda x: x["momentum"] * WEIGHTS["momentum"] + x["sentiment"] * WEIGHTS["sentiment"],
             reverse=True)
    shortlist = pre[:SHORTLIST_SIZE]
    fund = fetch_fundamentals([p["symbol"] for p in shortlist])

    ideas = []
    for p in shortlist:
        sym = p["symbol"]
        f_score, f_why = fundamental_score(sym, fund)
        wave = round(p["momentum"] * WEIGHTS["momentum"]
                     + p["sentiment"] * WEIGHTS["sentiment"]
                     + f_score * WEIGHTS["fundamentals"])
        ideas.append({
            "symbol": sym,
            "name": (fund.get(sym) or {}).get("name") or sent.get(sym, {}).get("name", sym),
            "theme": uni.get(sym, "—"),
            "wave_score": wave,
            "momentum": p["momentum"],
            "sentiment": p["sentiment"],
            "fundamentals": f_score,
            "close": mom[sym]["last_close"],
            "why": " · ".join(x for x in [p["m_why"], p["s_why"], f_why] if x),
        })
    ideas.sort(key=lambda x: x["wave_score"], reverse=True)
    return ideas, sent


def theme_pulse(price_data, sentiment):
    """Theme-level wave detection: is a whole basket moving, or one stock?"""
    mom = momentum_metrics(price_data)
    rows = []
    for theme, syms in THEMES.items():
        have = [s for s in syms if s in mom]
        if not have:
            continue
        rows.append({
            "Theme": theme,
            "Median 3-mo return": pd.Series([mom[s]["ret_3m"] for s in have]).median(),
            "Breadth above 200-day": sum(mom[s]["above_200sma"] for s in have) / len(have),
            "Reddit mentions": sum(sentiment.get(s, {}).get("mentions", 0) for s in have),
            "Names": len(have),
        })
    df = pd.DataFrame(rows)
    return df.sort_values("Median 3-mo return", ascending=False) if not df.empty else df


def new_on_radar(sentiment, limit=15):
    """Reddit-hot tickers *outside* the universe — where the next theme shows up first."""
    uni = universe()
    rows = []
    for sym, s in sentiment.items():
        if sym in uni or sym in _NOT_A_COMPANY or s["rank"] > 100 or looks_like_fund(s["name"]):
            continue
        prev = s["mentions_24h_ago"]
        rows.append({
            "Ticker": sym, "Name": s["name"], "Reddit rank": s["rank"],
            "Mentions": s["mentions"],
            "vs yesterday": f"{s['mentions'] / prev:.1f}x" if prev > 0 else "new",
        })
    rows.sort(key=lambda r: r["Reddit rank"])
    return pd.DataFrame(rows[:limit])
