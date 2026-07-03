"""
edgar.py — fetches straight from SEC EDGAR. Nothing paywalled, nothing
scraped from behind a login: 10-Ks, 10-Qs, and the exhibits companies
themselves file (like Amazon's annual shareholder letter, furnished as
Exhibit 99.1 to an 8-K every year). All free, all official, no API key.

True earnings-call transcripts (the verbatim analyst Q&A) aren't here on
purpose — those are mostly paywalled/ToS-restricted at Seeking Alpha, Motley
Fool, AlphaSense, etc. What IS here: the 10-K/10-Q themselves (which include
management's discussion & analysis) and the earnings press release, which
together cover the same ground with zero legal ambiguity.

SEC asks every caller to identify itself with a real contact in the
User-Agent header — see sec_contact_email in Settings.
"""

import os
import re
import json
import time

import requests
from bs4 import BeautifulSoup

APP_DIR = os.path.dirname(os.path.abspath(__file__))
TICKER_CACHE_PATH = os.path.join(APP_DIR, "ticker_cik_cache.json")

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"

MAX_CHARS = 600_000  # generous cap so we don't choke on a 12 MB 10-K


def _headers(contact_email: str = ""):
    contact = contact_email.strip() or "research-tool contact-not-set@example.com"
    return {
        "User-Agent": f"Read Between Lines (personal research tool) {contact}",
        "Accept-Encoding": "gzip, deflate",
    }


def _get(url, contact_email="", **kw):
    r = requests.get(url, headers=_headers(contact_email), timeout=30, **kw)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------------------
# Ticker -> CIK
# ---------------------------------------------------------------------------
def _load_ticker_map(contact_email="", force_refresh=False):
    if not force_refresh and os.path.exists(TICKER_CACHE_PATH):
        age_days = (time.time() - os.path.getmtime(TICKER_CACHE_PATH)) / 86400
        if age_days < 30:
            with open(TICKER_CACHE_PATH) as f:
                return json.load(f)

    data = _get(TICKERS_URL, contact_email).json()
    mapping = {row["ticker"].upper(): str(row["cik_str"]).zfill(10) for row in data.values()}
    with open(TICKER_CACHE_PATH, "w") as f:
        json.dump(mapping, f)
    return mapping


def get_cik(ticker, contact_email=""):
    """10-digit, zero-padded CIK for a ticker, or None if not found."""
    mapping = _load_ticker_map(contact_email)
    return mapping.get(ticker.upper())


# ---------------------------------------------------------------------------
# Filing listing + fetch (10-K / 10-Q)
# ---------------------------------------------------------------------------
def list_filings(cik10, forms=("10-K", "10-Q"), count=8, contact_email=""):
    """Most recent filings of the given form types, newest first."""
    data = _get(SUBMISSIONS_URL.format(cik10=cik10), contact_email).json()
    recent = data.get("filings", {}).get("recent", {})
    forms_list = recent.get("form", [])
    rows = []
    for i, form in enumerate(forms_list):
        if form not in forms:
            continue
        rows.append({
            "form": form,
            "filed_date": recent["filingDate"][i],
            "period": recent.get("reportDate", [""] * len(forms_list))[i],
            "accession": recent["accessionNumber"][i],
            "primary_doc": recent["primaryDocument"][i],
        })
    rows.sort(key=lambda r: r["filed_date"], reverse=True)
    return rows[:count]


def filing_url(cik10, accession, doc):
    cik_int = str(int(cik10))
    acc_nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"


def fetch_clean_text(url, contact_email=""):
    """Fetch an EDGAR HTML document and return readable plain text.

    Newlines go after block-level elements only; inline tags (EDGAR filings
    wrap nearly every phrase in a <span>) are joined with spaces, so sentences
    stay on one line — which is what lets the Highlights feature find the
    model's verbatim quotes in this text.
    """
    html = _get(url, contact_email).text
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all(["p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"]):
        tag.append("\n")
    for tag in soup.find_all("br"):
        tag.replace_with("\n")
    text = soup.get_text(" ")
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n\n[...truncated for length...]"
    return text


# ---------------------------------------------------------------------------
# Classic letters — curated, verified accession numbers for Amazon's annual
# shareholder letters (furnished as Exhibit 99.1 to an 8-K each spring).
# FY2007–FY2020 are all Jeff Bezos, and every exhibit reprints the original
# 1997 "It's All About the Long Term" letter as an appendix ("As always, I
# attach a copy of our original 1997 letter"), so the 1997 text is in each.
# Earlier letters (FY1998–FY2006) only appeared inside the glossy annual
# report, which isn't filed on EDGAR as a standalone exhibit.
# ---------------------------------------------------------------------------
AMZN_CIK10 = "0001018724"

AMZN_CLASSIC_LETTERS = [
    {"letter_year": "2007", "filed_date": "2008-04-18", "accession": "0001193125-08-084145", "doc": "dex991.htm"},
    {"letter_year": "2008", "filed_date": "2009-04-17", "accession": "0001193125-09-081096", "doc": "dex991.htm"},
    {"letter_year": "2009", "filed_date": "2010-04-14", "accession": "0001193125-10-082914", "doc": "dex991.htm"},
    {"letter_year": "2010", "filed_date": "2011-04-27", "accession": "0001193125-11-110797", "doc": "dex991.htm"},
    {"letter_year": "2011", "filed_date": "2012-04-13", "accession": "0001193125-12-161812", "doc": "d329990dex991.htm"},
    {"letter_year": "2012", "filed_date": "2013-04-12", "accession": "0001193125-13-151836", "doc": "d511111dex991.htm"},
    {"letter_year": "2013", "filed_date": "2014-04-10", "accession": "0001193125-14-137753", "doc": "d702518dex991.htm"},
    {"letter_year": "2014", "filed_date": "2015-04-24", "accession": "0001193125-15-144741", "doc": "d895323dex991.htm"},
    {"letter_year": "2015", "filed_date": "2016-04-05", "accession": "0001193125-16-530910", "doc": "d168744dex991.htm"},
    {"letter_year": "2016", "filed_date": "2017-04-12", "accession": "0001193125-17-120198", "doc": "d373368dex991.htm"},
    {"letter_year": "2017", "filed_date": "2018-04-18", "accession": "0001193125-18-121161", "doc": "d456916dex991.htm"},
    {"letter_year": "2018", "filed_date": "2019-04-11", "accession": "0001193125-19-103013", "doc": "d727605dex991.htm"},
    {"letter_year": "2019", "filed_date": "2020-04-16", "accession": "0001193125-20-108427", "doc": "d902615dex991.htm"},
    {"letter_year": "2020", "filed_date": "2021-04-15", "accession": "0001104659-21-050346", "doc": "tm216818d2_ex99-1.htm"},
]


def classic_letter_entries():
    """[{letter_year, filed_date, url, title}] for every known Bezos letter."""
    out = []
    for e in AMZN_CLASSIC_LETTERS:
        out.append({
            "letter_year": e["letter_year"],
            "filed_date": e["filed_date"],
            "accession": e["accession"],
            "title": f"Letter to Shareholders — FY{e['letter_year']}",
            "url": filing_url(AMZN_CIK10, e["accession"], e["doc"]),
        })
    return out
