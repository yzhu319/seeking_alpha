#!/usr/bin/env python3
"""
scanner.py — the "behind the scenes" half of AI Infra Watch.

This is what the OS scheduler runs quietly on its own (see the Alerts tab
in the app, or README.md for the manual cron / Task Scheduler steps). It
reads the watchlist and your alert settings from the same database the
dashboard uses, so anything you change in the app takes effect here on the
next scheduled run — no separate configuration, nothing to keep in sync by
hand.

It never opens a browser window and prints almost nothing; check
scanner.log (created next to this file) if you want to see its output, or
the History tab in the app, which reads from the same log table.
"""

import common


def main():
    common.init_db()
    watchlist = common.get_watchlist(enabled_only=True)
    if not watchlist:
        print("Watchlist is empty — nothing to scan.")
        return

    settings = common.get_settings()
    results = common.analyze_watchlist(watchlist, settings)
    if not results:
        print("No usable price data this run.")
        return

    common.log_results(results, watchlist)
    fresh = common.get_fresh_signals(results, watchlist)

    if fresh:
        ok, msg = common.send_alert(fresh, settings)
        print(f"{len(fresh)} fresh signal(s): {[s['symbol'] for s in fresh]} — {msg}")
    else:
        print("Scan complete — nothing fired.")


if __name__ == "__main__":
    main()
