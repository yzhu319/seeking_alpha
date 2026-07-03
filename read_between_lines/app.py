"""
app.py — Read Between Lines: an AI reading companion for 10-Ks, 10-Qs, and
classic shareholder letters. Independent from Wave Radar — run with:

    streamlit run app.py

(or double-click start_mac.command / start_windows.bat)
"""

import streamlit as st

import db
import edgar
import ai

st.set_page_config(page_title="Read Between Lines", page_icon="📖", layout="wide")
db.init_db()

st.title("📖 Read Between Lines")
st.caption(
    "An AI reading companion for earnings reports and shareholder letters — the long, dense, "
    "important stuff worth actually reading. Sources: SEC EDGAR only. Free, official, no paywalled transcripts."
)

settings = db.get_settings()
MODEL = settings.get("gemini_model") or "gemini-2.5-flash"
CONTACT = settings.get("sec_contact_email", "")

if not ai.has_key(settings):
    st.warning(
        "No Gemini API key yet — the reader still fetches and displays filings, but the AI features "
        "(TL;DR, Breakdown, Plain English, Highlights, Slides) need a key. Add one free from "
        "[aistudio.google.com/apikey](https://aistudio.google.com/apikey) in the ⚙️ Settings tab.",
        icon="🔑",
    )


# ---------------------------------------------------------------------------
# Shared: the AI toolbar shown under any filing or letter
# ---------------------------------------------------------------------------
def _get_or_generate(filing_id, feature, generate_fn):
    cached = db.get_ai_cache(filing_id, feature, MODEL)
    if cached is None:
        if st.button("✨ Generate", key=f"gen_{feature}_{filing_id}"):
            with st.spinner("Reading the document…"):
                result = generate_fn()
            # only cache successes — a failure (no key yet, rate limit, flaky
            # network) must stay retryable, not become the permanent answer
            if result.get("ok"):
                db.set_ai_cache(filing_id, feature, MODEL, result)
                st.rerun()  # re-render from cache, without the Generate button
            return result  # failure: show the message, keep the button for retry
        return None
    return cached


def render_ai_toolbar(filing_id, title, raw_text):
    sub_tldr, sub_break, sub_plain, sub_high, sub_slides, sub_raw = st.tabs(
        ["TL;DR", "🧩 Breakdown", "🗣️ Plain English", "🔦 Highlights", "🎞️ Slides", "📄 Full text"]
    )

    with sub_tldr:
        r = _get_or_generate(filing_id, "tldr", lambda: ai.tldr(raw_text, title, settings))
        if r:
            st.markdown(r["text"]) if r.get("ok") else st.info(r.get("message"))

    with sub_break:
        r = _get_or_generate(filing_id, "breakdown", lambda: ai.breakdown(raw_text, title, settings))
        if r:
            if r.get("ok"):
                for section, bullets in r["sections"].items():
                    st.markdown(f"#### {section}")
                    for b in bullets:
                        st.markdown(f"- {b}")
            else:
                st.info(r.get("message"))

    with sub_plain:
        r = _get_or_generate(filing_id, "plain_english", lambda: ai.plain_english(raw_text, title, settings))
        if r:
            st.markdown(r["text"]) if r.get("ok") else st.info(r.get("message"))

    with sub_high:
        r = _get_or_generate(filing_id, "highlights", lambda: ai.highlights(raw_text, title, settings))
        if r:
            if r.get("ok"):
                if not r["found"] and not r["missing"]:
                    st.info("Nothing came back — try Generate again.")
                for item in r["found"]:
                    st.markdown(f"> {item['quote']}")
                    st.caption(f"Why it matters: {item.get('why', '')}")
                if r["missing"]:
                    with st.expander(f"{len(r['missing'])} more (paraphrased — couldn't pin to an exact spot)"):
                        for item in r["missing"]:
                            st.markdown(f"- {item.get('quote', '')} — *{item.get('why', '')}*")
                if r["found"]:
                    with st.expander("📄 View full document with highlights marked"):
                        html = ai.highlighted_html(raw_text, r["found"])
                        st.markdown(
                            f'<div style="white-space:normal; line-height:1.7;">{html}</div>',
                            unsafe_allow_html=True,
                        )
            else:
                st.info(r.get("message"))

    with sub_slides:
        r = _get_or_generate(filing_id, "slides", lambda: ai.slides(raw_text, title, settings))
        if r:
            if r.get("ok") and r.get("slides"):
                deck = r["slides"]
                skey = f"slide_idx_{filing_id}"
                st.session_state.setdefault(skey, 0)
                idx = min(st.session_state[skey], len(deck) - 1)
                slide = deck[idx]

                st.markdown(f"### {slide.get('title', '')}")
                if slide.get("stat_value"):
                    st.metric(slide.get("stat_label") or "", slide["stat_value"])
                for b in slide.get("bullets", []) or []:
                    st.markdown(f"- {b}")

                colp, coln, colc = st.columns([1, 1, 3])
                if colp.button("⬅ Prev", key=f"prev_{filing_id}", disabled=idx == 0):
                    st.session_state[skey] = idx - 1
                    st.rerun()
                if coln.button("Next ➡", key=f"next_{filing_id}", disabled=idx >= len(deck) - 1):
                    st.session_state[skey] = idx + 1
                    st.rerun()
                colc.caption(f"Slide {idx + 1} of {len(deck)}")
            else:
                st.info(r.get("message", "Nothing generated."))

    with sub_raw:
        st.text_area("Full text", raw_text, height=500, key=f"rawtext_{filing_id}", label_visibility="collapsed")


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_read, tab_classic, tab_settings, tab_about = st.tabs(
    ["📖 Read", "🏛️ Classic Letters", "⚙️ Settings", "ℹ️ About"]
)

with tab_read:
    companies = db.get_companies()
    sectors = sorted({c["sector"] for c in companies})
    default_sector = sectors.index("eCommerce") if "eCommerce" in sectors else 0
    sector = st.selectbox("Sector", sectors, index=default_sector)

    sector_companies = [c for c in companies if c["sector"] == sector]
    labels = {c["ticker"]: f"{c['ticker']} — {c['name']}" for c in sector_companies}
    ticker = st.selectbox("Company", list(labels), format_func=lambda t: labels[t])

    if st.button("🔄 Fetch latest 10-K / 10-Q from EDGAR"):
        with st.spinner(f"Looking up {ticker} on SEC EDGAR…"):
            try:
                company = next(c for c in companies if c["ticker"] == ticker)
                cik = company["cik"] or edgar.get_cik(ticker, CONTACT)
                if not cik:
                    st.error(f"Couldn't find a CIK for {ticker} on SEC EDGAR.")
                else:
                    db.save_cik(ticker, cik)
                    listing = edgar.list_filings(cik, forms=("10-K", "10-Q"), count=6, contact_email=CONTACT)
                    added = 0
                    for f in listing:
                        url = edgar.filing_url(cik, f["accession"], f["primary_doc"])
                        if db.filing_exists(ticker, url):
                            continue
                        text = edgar.fetch_clean_text(url, CONTACT)
                        title = f"{ticker} {f['form']} — period {f['period'] or f['filed_date']}"
                        db.save_filing(ticker, f["form"], title, f["period"], f["filed_date"],
                                        f["accession"], url, text)
                        added += 1
                    st.success(f"Fetched {added} new filing(s)." if added else "Already up to date.")
            except Exception as e:
                st.error(f"Couldn't fetch from EDGAR: {e}")
        # no rerun: the filings list below is queried after this handler, so
        # new filings show up immediately — and the message above stays visible

    filings = db.get_filings(ticker)
    if not filings:
        st.info("No filings yet for this company — click **Fetch latest 10-K / 10-Q from EDGAR** above.")
    else:
        options = {f["id"]: f"{f['form']} · {f['period'] or '—'} · filed {f['filed_date']}" for f in filings}
        fid = st.selectbox("Filing", list(options), format_func=lambda i: options[i])
        chosen = next(f for f in filings if f["id"] == fid)
        st.caption(f"Source: {chosen['source_url']}")
        render_ai_toolbar(fid, chosen["title"] or options[fid], db.get_filing_text(fid))

with tab_classic:
    st.subheader("🏛️ Classic Letters — Jeff Bezos's Annual Letters to Shareholders")
    st.caption(
        "Bezos's annual letter doubled as a manifesto on long-term thinking, customer obsession, "
        "and how he actually reasoned about building value — the same tradition Warren Buffett is "
        "famous for at Berkshire. FY2007 through FY2020 here, sourced straight from Amazon's own "
        "SEC filings (Exhibit 99.1 to an 8-K each spring), not scraped from anywhere. And the "
        "famous original — the 1997 \"It's All About the Long Term\" letter — is in every one of "
        "them: Bezos reprinted it as an appendix each year (\"As always, I attach a copy of our "
        "original 1997 letter\")."
    )

    if st.button("🔄 Fetch classic letters (one-time)"):
        with st.spinner("Fetching Bezos's shareholder letters from SEC EDGAR…"):
            added, failed = 0, []
            for entry in edgar.classic_letter_entries():
                if db.filing_exists("AMZN", entry["url"]):
                    continue
                try:
                    text = edgar.fetch_clean_text(entry["url"], CONTACT)
                except Exception as e:
                    failed.append(f"{entry['title']} ({e})")
                    continue
                db.save_filing("AMZN", "LETTER", entry["title"], entry["letter_year"], entry["filed_date"],
                                entry["accession"], entry["url"], text,
                                is_classic_letter=True, letter_year=entry["letter_year"])
                added += 1
            st.success(f"Fetched {added} new letter(s)." if added else "Already up to date.")
            if failed:
                st.warning("Couldn't fetch: " + "; ".join(failed))

    letters = db.get_filings("AMZN", classic_only=True)
    if not letters:
        st.info("No letters fetched yet — click **Fetch classic letters** above.")
    else:
        options = {l["id"]: f"FY{l['letter_year']} — filed {l['filed_date']}" for l in letters}
        lid = st.selectbox("Letter", list(options), format_func=lambda i: options[i])
        chosen = next(l for l in letters if l["id"] == lid)
        st.caption(f"Source: {chosen['source_url']}")
        render_ai_toolbar(lid, chosen["title"], db.get_filing_text(lid))

with tab_settings:
    st.subheader("Gemini API key")
    st.caption("Stored locally in rbl.db, next to this app — nowhere else, no cloud account needed.")

    with st.form("gemini_form"):
        key = st.text_input(
            "Gemini API key", value=settings.get("gemini_api_key", ""), type="password",
            placeholder="paste your key — free at aistudio.google.com/apikey",
        )
        model = st.text_input("Model", value=settings.get("gemini_model", "gemini-2.5-flash"))
        contact = st.text_input(
            "Your email (SEC requires a real contact in every request's User-Agent)",
            value=settings.get("sec_contact_email", ""), placeholder="you@example.com",
        )
        saved = st.form_submit_button("💾 Save")

    if saved:
        db.update_settings({"gemini_api_key": key, "gemini_model": model, "sec_contact_email": contact})
        st.session_state["settings_saved"] = True
        st.rerun()  # so the key warning / MODEL read at the top of the page refresh
    if st.session_state.pop("settings_saved", False):
        st.success("Saved.")

    st.divider()
    st.subheader("AI cache")
    st.caption("Every AI feature is cached per filing + model, so it only costs an API call once. "
                "Clear it after changing the model, or if you just want a fresh take.")
    if st.button("🗑️ Clear AI cache"):
        db.clear_ai_cache()
        st.success("Cleared — everything regenerates next time you open it.")

with tab_about:
    st.subheader("About Read Between Lines")
    st.caption("An AI reading companion — not investment advice. Always check the source document.")

    c1, c2 = st.columns(2)
    c1.link_button("💻 Source code (GitHub)", "https://github.com/yzhu319/seeking_alpha", width="stretch")
    c2.link_button("📜 Data: SEC EDGAR full-text search", "https://www.sec.gov/edgar/search/", width="stretch")

    st.divider()
    st.markdown("#### Where your data lives")
    st.code(db.DB_PATH, language=None)
    st.markdown(
        "Every filing's raw text and every AI output live in one local SQLite file, right next to "
        "this app — back it up by copying that one file. Nothing is uploaded anywhere except the "
        "filing text sent to Google's Gemini API when you click Generate (and only once per "
        "filing/feature — after that it's served from cache)."
    )

    st.markdown("#### What's actually in here")
    st.markdown(
        "- **10-K / 10-Q** — the official annual and quarterly reports, straight from SEC EDGAR.\n"
        "- **Classic Letters** — Amazon's annual shareholder letters, also filed with the SEC "
        "(Exhibit 99.1 to an 8-K each spring) — not scraped from anywhere.\n"
        "- **Not included:** verbatim earnings-call Q&A transcripts. Those live behind paywalled "
        "or ToS-restricted services (Seeking Alpha, Motley Fool, AlphaSense) — there's no free, "
        "legal source for them, so this app sticks to the official filings, which cover the same "
        "ground (management's discussion, results, and outlook) without the legal ambiguity."
    )

    st.markdown("#### AI features")
    st.markdown(
        "- **TL;DR** — a 5-bullet summary plus a one-line verdict.\n"
        "- **Breakdown** — structured sections: business, revenue, margins, balance sheet, "
        "guidance, risks, management tone.\n"
        "- **Plain English** — explained with zero jargon, written for someone new to investing.\n"
        "- **Highlights** — the sentences worth circling, as quote cards and marked directly in "
        "the full document.\n"
        "- **Slides** — the filing restructured into a browsable, in-app investor deck.\n\n"
        "All powered by Gemini (add your API key in ⚙️ Settings — get one free at "
        "[aistudio.google.com/apikey](https://aistudio.google.com/apikey)). AI output can be "
        "wrong or incomplete — treat it as a fast first pass, not a substitute for reading the "
        "source yourself."
    )
