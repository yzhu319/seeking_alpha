# Read Between Lines

An AI reading companion for earnings reports and shareholder letters — the
long, dense, important stuff worth actually reading, the way Warren Buffett
famously does. Independent from the Wave Radar app in this repo; it has its
own database, its own dependencies, its own start scripts.

Point it at a company, pull its 10-K/10-Q straight from SEC EDGAR (free,
official, no login), and let AI walk you through it: a TL;DR, a structured
breakdown, a plain-English explainer, the sentences worth circling, and the
whole thing restructured into a browsable slide deck. Starts with the
eCommerce sector (Amazon, Shopify, Walmart, Instacart) and includes a
**Classic Letters** section — Jeff Bezos's annual shareholder letters,
FY2007–FY2020, in the same tradition as Buffett's Berkshire letters. (The
famous 1997 "It's All About the Long Term" letter is in every one of them:
Bezos reprinted it as an appendix each year. Letters before FY2007 only
appeared inside the glossy annual report, which isn't on EDGAR.)

**Not investment advice.** AI summaries can be wrong or incomplete — treat
them as a fast first pass, not a substitute for reading the source.

---

## What it does and doesn't fetch

- **10-K / 10-Q** — the official annual/quarterly reports, straight from
  SEC EDGAR.
- **Classic Letters** — Amazon's annual shareholder letters, also SEC
  filings (Exhibit 99.1 to an 8-K each spring) — not scraped from anywhere.
- **Not included: verbatim earnings-call transcripts.** The actual analyst
  Q&A is mostly paywalled or ToS-restricted (Seeking Alpha, Motley Fool,
  AlphaSense) — there's no clean free/legal source. The 10-K/10-Q and
  earnings press releases cover the same substance (results, management's
  discussion, outlook) without that ambiguity.

Everything fetched is public and free — no subscriptions, no API fees for
the data itself.

## 1. One-time setup

Same as the rest of this repo: install Python 3 from
[python.org/downloads](https://www.python.org/downloads/) if you don't have
it (Windows: check "Add python.exe to PATH" in the installer).

You'll also want a **free Gemini API key** for the AI features — get one at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey), then paste
it into the app's Settings tab. Without a key, you can still fetch and read
filings — just not the AI features.

## 2. Start the app

- **Mac:** double-click `start_mac.command` (first time: right-click → Open
  → Open, to get past macOS's unsigned-script warning).
- **Windows:** double-click `start_windows.bat`.

Your browser opens automatically at `http://localhost:8502`. This app runs
on its own port, separate from Wave Radar (which uses 8501) — both can run
at the same time.

## 3. Using it

Four tabs:

- **📖 Read** — pick a sector (starts with eCommerce) and a company, click
  **Fetch latest 10-K / 10-Q**, then pick a filing. Under it: TL;DR,
  Breakdown, Plain English, Highlights, Slides, and the full raw text —
  each generated on demand and cached, so you only pay the API call once.
- **🏛️ Classic Letters** — click **Fetch classic letters** once to pull
  Bezos's annual letters (FY2007–FY2020, each with the 1997 original as an
  appendix) from SEC EDGAR, then read any of them with the same AI toolbar.
- **⚙️ Settings** — your Gemini API key, model name, and the email SEC
  wants in every request's User-Agent (just a courtesy identifier, not an
  account).
- **ℹ️ About** — where the data lives, what is/isn't sourced, links back to
  the code.

## Where your data lives

Everything — fetched filings and every AI output — lives in one file,
`rbl.db`, right next to this app. Nothing is uploaded anywhere except the
filing text sent to Google's Gemini API when you click Generate (and after
that, results are cached locally, not re-sent).
