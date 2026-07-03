#!/usr/bin/env python3
"""
scanner.py — the "behind the scenes" half of Wave Radar.

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
import ideas as idea_engine


def main():
    common.init_db()
    watchlist = common.get_watchlist(enabled_only=True)
    settings = common.get_settings()

    # One download covering the theme universe plus the user's watchlist.
    uni_map = idea_engine.universe()
    all_syms = sorted(set(uni_map) | {w["symbol"] for w in watchlist})
    all_results = common.analyze_watchlist([{"symbol": s} for s in all_syms], settings)
    if not all_results:
        print("No usable price data this run.")
        return

    # Classic breakout alerts on the user's watchlist.
    watch_symbols = {w["symbol"] for w in watchlist}
    results = {s: df for s, df in all_results.items() if s in watch_symbols}
    if results:
        common.log_results(results, watchlist)
        fresh = common.get_fresh_signals(results, watchlist)
        if fresh:
            ok, msg = common.send_alert(fresh, settings)
            print(f"{len(fresh)} fresh breakout(s): {[s['symbol'] for s in fresh]} — {msg}")
        else:
            print("Breakout scan — nothing fired.")

    # Wave Radar ideas across the whole universe.
    ideas, _ = idea_engine.generate_ideas(all_results, all_results, settings)
    hot = common.ideas_needing_alert(ideas, int(settings["idea_alert_threshold"]))
    common.log_ideas(ideas)
    if hot:
        ok, msg = common.send_idea_alert(hot, settings)
        print(f"{len(hot)} hot idea(s): {[i['symbol'] for i in hot]} — {msg}")
    else:
        print("Idea scan — nothing crossed the threshold.")


if __name__ == "__main__":
    main()
