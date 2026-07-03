# AI Infra Watch

A private dashboard, just for you, that watches a basket of AI-infrastructure
stocks (chips, memory, cooling, networking, power) for breakouts — and can
text or email you when one happens. Everything runs on this laptop. Nothing
is uploaded anywhere, no account required, no cloud bill.

**Not investment advice.** A transparent, rules-based screen — useful as one
input, not a substitute for your own judgment.

---

## 1. One-time setup

You need Python installed once. If you're not sure you have it:

- **Mac:** open Spotlight (⌘+Space), type "Terminal", press Enter. Type
  `python3 --version` and press Enter. If you see a version number, you're
  set — skip to step 2. If not, install from
  [python.org/downloads](https://www.python.org/downloads/) (just click
  through the installer with defaults).
- **Windows:** install from
  [python.org/downloads](https://www.python.org/downloads/). **Important:**
  on the first screen of the installer, check the box "Add python.exe to
  PATH" before clicking Install.

## 2. Start the app

- **Mac:** double-click `start_mac.command`.
  - First time only, macOS will refuse with "unidentified developer" —
    right-click the file → **Open** → **Open** again. After that, double-
    click works normally.
- **Windows:** double-click `start_windows.bat`.

The first launch takes a minute or two (it's quietly installing a few
things). Your browser will open automatically to the dashboard. Every time
after this, starting it is just: double-click, wait a few seconds, browser
opens.

To stop it: close the terminal/command window that opened alongside it.

## 3. Using it

Five tabs, left to right:

- **Market Pulse** — the headline. What fired today, at a glance.
- **Time Machine** — drag the slider to any past date and see what the
  rules would have flagged then, with no hindsight. "Jump to first
  breakout" finds whatever the rules actually caught first.
- **Watchlist** — add or remove tickers directly in the table. No code,
  just type a symbol and hit save. Un-check "Active" to pause a name
  without deleting it.
- **Alerts** — set up email/text notifications and turn on background
  checking (see below).
- **History** — a running log of everything the dashboard (and the
  background checker) have found, over time. This is what eventually lets
  you judge whether the rules are actually any good.

## 4. Getting alerts on your phone or email

Open the **Alerts** tab.

**Email:** if you use Gmail, you'll need an
[app password](https://myaccount.google.com/apppasswords) (a 16-character
code Google generates for exactly this purpose) — your regular Gmail
password won't work here. Put `smtp.gmail.com` as the server, port `587`,
your Gmail address, and the app password.

**Text messages, for free:** every carrier has a hidden email address that
turns into a text. Use the "Turn a phone number into a text address" box in
the Alerts tab and it builds this for you automatically. Under the hood:

| Carrier  | Gateway                        |
|----------|----------------------------------|
| AT&T     | number@txt.att.net               |
| T-Mobile | number@tmomail.net               |
| Verizon  | number@vtext.com                 |
| Sprint   | number@messaging.sprintpcs.com   |

Hit **"Send a test alert"** to confirm it actually reaches you before
relying on it.

## 5. Background checking (the "behind the scenes" part)

By default, the dashboard only checks the market while it's open in your
browser. Flip on **"Turn on background checking"** in the Alerts tab, and
your laptop's own scheduler (cron on Mac, Task Scheduler on Windows) will
run the check quietly on the interval you pick — you'll get a text/email
if something fires, without ever opening the app. Turn it off the same way.

**One macOS quirk:** the first time, macOS may need you to grant Terminal
(or cron) permission under **System Settings → Privacy & Security → Full
Disk Access**. If background checks don't seem to be firing after a day,
that's the usual reason — grant access there and it'll start working.

**If the automatic setup ever fails** (some work laptops restrict this),
the two-line manual version — Mac/Linux Terminal:

```
crontab -e
0 */2 * * 1-5 /path/to/ai_infra_app/.venv/bin/python /path/to/ai_infra_app/scanner.py
```

Windows: Task Scheduler → Create Basic Task → Trigger "Daily" repeating
every N hours → Action "Start a program" → point it at
`ai_infra_app\.venv\Scripts\python.exe` with argument `scanner.py`.

## Where your data lives

Everything — your watchlist, your alert settings, your signal history —
lives in one file: `ai_infra.db`, sitting right next to the app on this
laptop. It's a plain SQLite database; back it up by copying that one file.

You mentioned Google Cloud Storage — deliberately skipped it here. For a
single-user, single-laptop tool, a local file is simpler, needs no account
linking or credentials, and works offline. If you ever want the dashboard
reachable from your phone or a second device, that's the point where moving
the database to the cloud (or deploying the app itself) starts to earn its
complexity — happy to build that if/when you want it.

## Notes

- Price data is free, via Yahoo Finance, refreshed every 30 minutes on the
  dashboard (or on whatever interval you set for background checks). Free
  data occasionally has gaps or a short outage; the app skips whatever it
  can't fetch rather than failing entirely.
- The signal rules (tucked under "Advanced" in the Watchlist tab) default
  to: a new 60-day high, on 1.3x average volume, inside an uptrend, with a
  10-day cooldown so one move doesn't alert you five times.
- This has been tested for correctness — logic, error handling, the
  Streamlit UI itself — using synthetic data end-to-end. It has **not**
  been tested for how good the signal actually is; the History tab is what
  will eventually tell you that.
