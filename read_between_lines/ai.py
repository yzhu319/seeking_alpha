"""
ai.py — the "teacher" that walks you through a filing. A thin wrapper around
the Gemini API: five features (tldr, breakdown, plain_english, highlights,
slides), each just a prompt + a bit of JSON parsing. app.py caches every
result in db.ai_cache, so a given filing is only ever sent to the model once
per feature/model combination.

No key configured yet? Every function returns a friendly stub instead of
raising, so the rest of the app still renders — add a Gemini API key in the
Settings tab to switch these on.
"""

import json
import re

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:  # library not installed yet in this environment
    genai = None
    genai_types = None

# A full 10-K extracts to ~300k-1M chars; gemini-2.5-flash takes 1M tokens,
# so 400k chars (~100k tokens) fits comfortably while keeping latency sane.
# When a document is longer, keep the front (business, risk factors, MD&A)
# AND the back (financial statements, notes) — the middle is the safest cut.
MAX_INPUT_CHARS = 400_000
HEAD_CHARS = 300_000
TAIL_CHARS = 100_000


def has_key(settings: dict) -> bool:
    return bool(settings.get("gemini_api_key", "").strip()) and genai is not None


def _not_ready(settings, feature_label):
    """The stub dict to show instead of calling Gemini, or None if we're good to go."""
    if genai is None:
        return {
            "ok": False,
            "message": "The google-genai package isn't installed — rerun the start script "
                       "(or `pip install -r requirements.txt`).",
        }
    if not settings.get("gemini_api_key", "").strip():
        return {
            "ok": False,
            "message": f"Add a Gemini API key in the ⚙️ Settings tab to generate a {feature_label}.",
        }
    return None


def _truncate(text: str) -> str:
    if len(text) <= MAX_INPUT_CHARS:
        return text
    return (text[:HEAD_CHARS]
            + "\n\n[... middle of document truncated for length ...]\n\n"
            + text[-TAIL_CHARS:])


def _call(settings, prompt, json_mode=False):
    client = genai.Client(api_key=settings["gemini_api_key"].strip())
    config = genai_types.GenerateContentConfig(response_mime_type="application/json") if json_mode else None
    resp = client.models.generate_content(
        model=settings.get("gemini_model") or "gemini-2.5-flash",
        contents=prompt,
        config=config,
    )
    return resp.text


def _safe_json(raw: str):
    """Gemini in JSON mode is usually clean, but strip stray code fences just in case."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
    return json.loads(cleaned)


# ---------------------------------------------------------------------------
# Feature 1 — TL;DR
# ---------------------------------------------------------------------------
def tldr(text, title, settings):
    err = _not_ready(settings, "TL;DR")
    if err:
        return err
    prompt = f"""You are a sharp, no-nonsense equity analyst briefing a busy investor on "{title}".

Write a TL;DR with exactly 5 bullet points (plain sentences, no jargon left unexplained), covering:
1. What happened this period, in one line
2. Revenue & growth
3. Profitability / margins
4. Guidance or outlook (if any)
5. The single biggest risk or thing to watch

End with one bold-worthy verdict sentence.

DOCUMENT:
{_truncate(text)}"""
    try:
        return {"ok": True, "text": _call(settings, prompt)}
    except Exception as e:
        return {"ok": False, "message": f"Gemini call failed: {e}"}


# ---------------------------------------------------------------------------
# Feature 2 — Breakdown (structured sections)
# ---------------------------------------------------------------------------
BREAKDOWN_SECTIONS = [
    "Business Overview", "Revenue & Growth", "Profitability & Margins",
    "Balance Sheet & Cash Flow", "Guidance & Outlook", "Risks & Red Flags",
    "Management Tone",
]


def breakdown(text, title, settings):
    err = _not_ready(settings, "breakdown")
    if err:
        return err
    sections_list = ", ".join(f'"{s}"' for s in BREAKDOWN_SECTIONS)
    prompt = f"""Break "{title}" down into sections for an investor who wants the substance without
reading the whole thing. Return ONLY a JSON object with exactly these keys: {sections_list}.
Each value is a list of 2-5 short bullet strings (facts/figures from the document, not generic
commentary). If a section genuinely isn't covered in the document, use ["Not discussed in this document."].

DOCUMENT:
{_truncate(text)}"""
    try:
        raw = _call(settings, prompt, json_mode=True)
        data = _safe_json(raw)
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object of sections")
        # keep our section order, coerce every value to a list of strings
        sections = {}
        for name in BREAKDOWN_SECTIONS:
            bullets = data.get(name)
            if isinstance(bullets, str):
                bullets = [bullets]
            if not isinstance(bullets, list) or not bullets:
                bullets = ["Not discussed in this document."]
            sections[name] = [str(b) for b in bullets]
        return {"ok": True, "sections": sections}
    except Exception as e:
        return {"ok": False, "message": f"Gemini call failed or returned unparseable output: {e}"}


# ---------------------------------------------------------------------------
# Feature 3 — Plain English ("explain to mom and dad")
# ---------------------------------------------------------------------------
def plain_english(text, title, settings):
    err = _not_ready(settings, "plain-English explainer")
    if err:
        return err
    prompt = f"""Explain "{title}" to someone with zero finance background — your smart parent who's
never read a financial filing. No jargon (or if you must use a term, define it in the same
sentence with a real-world analogy). 3-4 warm, clear paragraphs: what the business actually did,
whether it's doing well and why, and what to make of the outlook. Skip disclaimers and boilerplate.

DOCUMENT:
{_truncate(text)}"""
    try:
        return {"ok": True, "text": _call(settings, prompt)}
    except Exception as e:
        return {"ok": False, "message": f"Gemini call failed: {e}"}


# ---------------------------------------------------------------------------
# Feature 4 — Highlights (key verbatim excerpts)
# ---------------------------------------------------------------------------
def highlights(text, title, settings):
    err = _not_ready(settings, "highlight reel")
    if err:
        return err
    prompt = f"""Pick the 8 most important sentences from "{title}" — the ones a careful investor
would circle in pen. Each MUST be copied VERBATIM from the document below (exact words, so it can
be found with a text search) — do not paraphrase or summarize. Return ONLY a JSON list of objects:
[{{"quote": "<exact sentence from the document>", "why": "<one clause on why it matters>"}}, ...]

DOCUMENT:
{_truncate(text)}"""
    try:
        raw = _call(settings, prompt, json_mode=True)
        data = _safe_json(raw)
        # keep only quotes we can actually locate, so the highlighted-document view is honest
        found, missing = [], []
        for item in data:
            if not isinstance(item, dict):
                continue
            q = (item.get("quote") or "").strip()
            item["quote"] = q
            pat = _quote_pattern(q)
            (found if pat and pat.search(text) else missing).append(item)
        if not found and not missing:
            return {"ok": False, "message": "The model returned no quotes — try Generate again."}
        return {"ok": True, "found": found, "missing": missing}
    except Exception as e:
        return {"ok": False, "message": f"Gemini call failed or returned unparseable output: {e}"}


# EDGAR filings use typographic quotes/dashes (it’s, “Day 1”, 2019–2020) but
# models usually quote back in plain ASCII — treat the variants as equal.
_CHAR_EQUIV = {}
for group in ["'’‘", '"“”', "-–—"]:
    for ch in group:
        _CHAR_EQUIV[ch] = f"[{group}]"


def _quote_pattern(quote):
    """Regex matching the quote with flexible whitespace and quote/dash style.
    The extracted filing text keeps newlines where HTML tags were and curly
    punctuation, but the model quotes with normal spaces and ASCII — so an
    exact substring test would reject genuinely verbatim quotes."""
    words = []
    for w in quote.split():
        words.append("".join(_CHAR_EQUIV.get(ch, re.escape(ch)) for ch in w))
    return re.compile(r"\s+".join(words)) if words else None


def highlighted_html(text, found_quotes):
    """Full document text as HTML with each found quote wrapped in <mark>."""
    import html as _html
    escaped = _html.escape(text)
    for item in found_quotes:
        pat = _quote_pattern(item.get("quote", ""))
        m = pat.search(text) if pat else None
        if not m:
            continue
        # mark the span as it actually appears in the document, not the model's version
        q = _html.escape(m.group(0))
        escaped = escaped.replace(q, f'<mark title="{_html.escape(item.get("why", ""))}">{q}</mark>', 1)
    return escaped.replace("\n", "<br>")


# ---------------------------------------------------------------------------
# Feature 5 — Slides (in-app interactive deck)
# ---------------------------------------------------------------------------
def slides(text, title, settings):
    err = _not_ready(settings, "slide deck")
    if err:
        return err
    prompt = f"""Turn "{title}" into a 7-9 slide investor deck. Return ONLY a JSON list of slide
objects, each: {{"title": "<slide title>", "bullets": ["<point>", ...] (2-4 items),
"stat_label": "<optional single headline number's label, or null>",
"stat_value": "<that number as a short string, or null>"}}.
Slide 1 should be a cover (company + period). Include headline numbers, revenue breakdown,
profitability, guidance, key risks, a standout management quote, and a bottom-line verdict slide.

DOCUMENT:
{_truncate(text)}"""
    try:
        raw = _call(settings, prompt, json_mode=True)
        data = _safe_json(raw)
        if isinstance(data, dict):  # sometimes comes back wrapped as {"slides": [...]}
            data = data.get("slides", [])
        deck = [s for s in data if isinstance(s, dict)] if isinstance(data, list) else []
        if not deck:
            raise ValueError("no slides in the response")
        return {"ok": True, "slides": deck}
    except Exception as e:
        return {"ok": False, "message": f"Gemini call failed or returned unparseable output: {e}"}
