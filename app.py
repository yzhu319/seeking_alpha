"""
app.py — Wave Radar, the dashboard.

Run this with:  streamlit run app.py
(or just double-click start_mac.command / start_windows.bat)
"""

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common
import ideas as idea_engine

st.set_page_config(page_title="Wave Radar", page_icon="🌊", layout="wide")
common.init_db()

st.title("🌊 Wave Radar")
st.caption(
    "Hunts for the big waves — price momentum + Reddit crowd ignition + fundamental thrust, "
    "scored mechanically across a universe of thematic baskets. "
    "Not investment advice: a transparent, rules-based screen to make sure you at least *see* the wave."
)

watchlist = common.get_watchlist(enabled_only=True)
settings = common.get_settings()

uni_map = idea_engine.universe()
all_symbols = tuple(sorted(set(uni_map) | {w["symbol"] for w in watchlist}))
watch_symbols = {w["symbol"] for w in watchlist}


@st.cache_data(ttl=1800, show_spinner="Scanning the whole universe — prices, Reddit, fundamentals…")
def cached_wave_scan(symbols_tuple, watchlist_tuple, settings_tuple):
    """
    One shared scan per refresh window: breakout signals for every symbol,
    ranked ideas, and all logging/alerting side effects (kept in here so they
    run once per scan, not on every widget interaction).
    """
    st_dict = dict(settings_tuple)
    wl = [dict(zip(["symbol", "name", "sector", "enabled"], w)) for w in watchlist_tuple]
    results = common.analyze_watchlist([{"symbol": s} for s in symbols_tuple], st_dict)
    sentiment = idea_engine.fetch_sentiment()
    idea_list, _ = idea_engine.generate_ideas(results, results, st_dict, sentiment)

    watch_results = {s: df for s, df in results.items() if s in {w["symbol"] for w in wl}}
    if watch_results:
        common.log_results(watch_results, wl)

    # Find not-yet-flagged hot ideas BEFORE logging today's scores, then alert.
    hot = common.ideas_needing_alert(idea_list, int(st_dict["idea_alert_threshold"]))
    common.log_ideas(idea_list)
    if hot:
        common.send_idea_alert(hot, st_dict)
    return results, idea_list, sentiment, hot


settings_tuple = tuple(sorted(settings.items()))
wl_tuple = tuple((w["symbol"], w["name"], w["sector"], w["enabled"]) for w in watchlist)

all_results, idea_list, sentiment, hot_ideas = {}, [], {}, []
fetch_error = None
try:
    all_results, idea_list, sentiment, hot_ideas = cached_wave_scan(all_symbols, wl_tuple, settings_tuple)
except Exception as e:
    fetch_error = str(e)

# The classic breakout tabs keep operating on *your* watchlist only.
results = {s: df for s, df in all_results.items() if s in watch_symbols}

tab_radar, tab_themes, tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["🌊 Idea Radar", "🧭 Theme Pulse", "📡 Breakouts", "⏱️ Time Machine", "📋 Watchlist", "🔔 Alerts", "📜 History"]
)

# ---------------------------------------------------------------------------
# Tab — Idea Radar (the headline: ranked, explained ideas)
# ---------------------------------------------------------------------------
with tab_radar:
    if fetch_error:
        st.error(f"Couldn't reach the market data provider right now: {fetch_error}")
    elif not idea_list:
        st.warning("No ideas could be scored yet — data may still be warming up. Try Refresh.")
    else:
        top = idea_list[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("Strongest wave right now", f"{top['symbol']} · {top['wave_score']}/100")
        c2.metric("Universe scanned", f"{len(all_results)} names, {len(idea_engine.THEMES)} themes")
        c3.metric("Alert threshold", f"≥ {int(settings['idea_alert_threshold'])}/100")

        if hot_ideas:
            st.success(
                "🔥 " + ", ".join(f"{i['symbol']} ({i['wave_score']})" for i in hot_ideas)
                + " crossed your alert threshold today."
            )

        st.markdown("#### Ranked ideas")
        st.caption(
            "Wave Score = 40% price wave + 25% crowd ignition + 35% fundamental thrust. "
            "Expand a row for the full 'why'. The score detects forming waves — it does not predict."
        )
        for i in idea_list[:15]:
            heat = "🔥" if i["wave_score"] >= int(settings["idea_alert_threshold"]) else ("🌊" if i["wave_score"] >= 55 else "·")
            with st.expander(
                f"{heat} **{i['symbol']}** — {i['name']}  ·  {i['theme']}  ·  "
                f"Wave {i['wave_score']}/100  ·  ${i['close']:.2f}"
            ):
                b1, b2, b3 = st.columns(3)
                b1.metric("Price wave", f"{i['momentum']}/100")
                b2.metric("Crowd ignition", f"{i['sentiment']}/100")
                b3.metric("Fundamental thrust", f"{i['fundamentals']}/100")
                st.write(i["why"])

        st.markdown("#### 👀 New on the radar (outside the universe)")
        st.caption(
            "Reddit-hot names not in any theme basket — where the *next* theme tends to show up first. "
            "Add promising ones to your watchlist."
        )
        radar_df = idea_engine.new_on_radar(sentiment)
        if radar_df.empty:
            st.info("Nothing unusual trending outside the universe right now.")
        else:
            st.dataframe(radar_df, hide_index=True, width="stretch")

        if st.button("🔄 Refresh scan"):
            st.cache_data.clear()
            st.rerun()

# ---------------------------------------------------------------------------
# Tab — Theme Pulse (is a whole basket moving, or just one stock?)
# ---------------------------------------------------------------------------
with tab_themes:
    st.subheader("Theme-level waves")
    st.caption(
        "A real wave lifts a whole basket, not one ticker — breadth is what separated the AI-infra boom "
        "from a meme squeeze. Sorted by median 3-month basket return."
    )
    if not all_results:
        st.info("No data yet.")
    else:
        pulse = idea_engine.theme_pulse(all_results, sentiment)
        if pulse.empty:
            st.info("No data yet.")
        else:
            st.dataframe(
                pulse,
                hide_index=True, width="stretch",
                column_config={
                    "Median 3-mo return": st.column_config.NumberColumn(format="percent"),
                    "Breadth above 200-day": st.column_config.ProgressColumn(min_value=0, max_value=1),
                },
            )
            best = pulse.iloc[0]
            st.metric(
                "Hottest theme",
                best["Theme"],
                f"{best['Median 3-mo return']:+.0%} median 3-mo, {best['Breadth above 200-day']:.0%} of names in uptrend",
            )

# ---------------------------------------------------------------------------
# Tab 1 — Breakouts (your watchlist)
# ---------------------------------------------------------------------------
with tab1:
    if not watchlist:
        st.info("Your watchlist is empty — add some names in the Watchlist tab.")
    elif fetch_error:
        st.error(f"Couldn't reach the market data provider right now: {fetch_error}")
    elif not results:
        st.warning("Not enough price history yet for any watchlist name — check back after the first full day.")
    else:
        fresh = common.get_fresh_signals(results, watchlist)
        c1, c2, c3 = st.columns(3)
        c1.metric("Fresh breakouts today", f"{len(fresh)} / {len(results)}")
        c2.metric("Watchlist size", f"{len(watchlist)} names")
        c3.metric("Last checked", datetime.now().strftime("%-I:%M %p"))

        if fresh:
            st.success(f"{len(fresh)} name(s) just confirmed a breakout.")
            show = pd.DataFrame(fresh)[["symbol", "name", "sector", "close", "date"]]
            show.columns = ["Ticker", "Name", "Sector", "Price", "Fired on"]
            st.dataframe(show, hide_index=True, width="stretch")
        else:
            st.info("Nothing fired today — that's normal. Breakouts aren't an everyday event by design.")

        if st.button("🔄 Refresh now"):
            st.cache_data.clear()
            st.rerun()

# ---------------------------------------------------------------------------
# Tab 2 — Time Machine
# ---------------------------------------------------------------------------
with tab2:
    st.subheader("Replay any date — no lookahead")
    st.caption("The score below is recomputed using only the data that existed on the date you pick.")

    if len(results) < 2:
        st.info("Need at least two names with enough history to build the index.")
    else:
        master_dates = sorted(set.intersection(*[set(df.index) for df in results.values()]))
        cooldown = int(settings["cooldown"])

        if len(master_dates) < cooldown + 5:
            st.info("Not enough overlapping history yet.")
        else:
            base = {sym: results[sym].loc[master_dates[0], "Close"] for sym in results}
            comp_index = [
                sum(results[sym].loc[d, "Close"] / base[sym] for sym in results) / len(results) * 100
                for d in master_dates
            ]

            score = []
            for d in master_dates:
                active = 0
                for sym, df in results.items():
                    loc = df.index.get_loc(d)
                    window = df.iloc[max(0, loc - cooldown + 1): loc + 1]
                    if window["fired"].any():
                        active += 1
                score.append(round(active / len(results) * 100))

            first_breakout = next((d for d, s in zip(master_dates, score) if s >= 50), None)

            if "playhead" not in st.session_state or st.session_state.playhead not in master_dates:
                default_idx = max(0, len(master_dates) - 1 - 105)  # ~5 months back
                st.session_state.playhead = master_dates[default_idx]

            def _jump_first():
                if first_breakout is not None:
                    st.session_state.playhead = first_breakout

            def _jump_today():
                st.session_state.playhead = master_dates[-1]

            colA, colB = st.columns(2)
            colA.button("⚡ Jump to first breakout", on_click=_jump_first, disabled=first_breakout is None,
                        width="stretch")
            colB.button("📍 Jump to today", on_click=_jump_today, width="stretch")

            playhead = st.select_slider(
                "Time travel to:", options=master_dates, key="playhead",
                format_func=lambda d: d.strftime("%b %d, %Y"),
            )
            pidx = master_dates.index(playhead)

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=master_dates, y=comp_index, name="Basket index",
                                      line=dict(color="#2E8B57", width=2)))
            fig.add_trace(go.Scatter(x=master_dates, y=score, name="Breakout score %", yaxis="y2",
                                      fill="tozeroy", line=dict(color="#E8A33D", width=1), opacity=0.5))
            fig.add_vline(x=playhead, line_dash="dash", line_color="gray")
            fig.update_layout(
                height=420, margin=dict(l=10, r=10, t=30, b=10),
                legend=dict(orientation="h", y=1.12),
                yaxis=dict(title="Basket index (rebased to 100)"),
                yaxis2=dict(title="Breakout score %", overlaying="y", side="right", range=[0, 100]),
            )
            st.plotly_chart(fig, width="stretch")

            hindsight = (comp_index[-1] / comp_index[pidx] - 1) * 100
            st.metric(f"Basket return, {playhead.strftime('%b %d, %Y')} → today", f"{hindsight:+.1f}%")

            rows = []
            meta = {w["symbol"]: w for w in watchlist}
            for sym, df in results.items():
                loc = df.index.get_loc(playhead)
                window = df.iloc[max(0, loc - cooldown + 1): loc + 1]
                fires = window[window["fired"]]
                fired = not fires.empty
                frow = fires.iloc[-1] if fired else None
                rows.append(
                    {
                        "Ticker": sym,
                        "Sector": meta.get(sym, {}).get("sector", ""),
                        "Signal": "Active" if fired else "—",
                        "Fired on": frow.name.strftime("%b %d, %Y") if fired else "—",
                        "Price @ fire": f"${frow['Close']:.2f}" if fired else "—",
                        "Return to today": f"{(df['Close'].iloc[-1] / frow['Close'] - 1) * 100:+.1f}%" if fired else "—",
                    }
                )
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Tab 3 — Watchlist
# ---------------------------------------------------------------------------
with tab3:
    st.subheader("Your watchlist")
    st.caption("Add or remove names here — the background checker picks up changes on its next run.")

    df_wl = pd.DataFrame(common.get_watchlist())
    if df_wl.empty:
        df_wl = pd.DataFrame(columns=["symbol", "name", "sector", "enabled"])
    df_wl["enabled"] = df_wl["enabled"].astype(bool)

    edited = st.data_editor(
        df_wl, num_rows="dynamic", hide_index=True, width="stretch",
        column_config={
            "symbol": st.column_config.TextColumn("Ticker", required=True),
            "name": st.column_config.TextColumn("Name"),
            "sector": st.column_config.TextColumn("Sector"),
            "enabled": st.column_config.CheckboxColumn("Active"),
        },
        key="watchlist_editor",
    )

    if st.button("💾 Save watchlist"):
        common.save_watchlist(edited.to_dict("records"))
        st.cache_data.clear()
        st.success("Saved.")
        st.rerun()

    with st.expander("Advanced: signal rules"):
        st.caption("Same defaults used everywhere in this app — change only if you know what you're loosening.")
        c1, c2, c3 = st.columns(3)
        lookback = c1.number_input("Breakout lookback (days)", 10, 250, int(settings["lookback_high"]))
        vol_window = c1.number_input("Volume average window (days)", 5, 60, int(settings["vol_window"]))
        sma_fast = c2.number_input("Fast trend average (days)", 5, 60, int(settings["sma_fast"]))
        sma_slow = c2.number_input("Slow trend average (days)", 10, 200, int(settings["sma_slow"]))
        vol_mult = c3.number_input("Volume confirmation multiple", 1.0, 5.0, float(settings["vol_mult"]), step=0.1)
        cooldown = c3.number_input("Cooldown between fires (days)", 1, 60, int(settings["cooldown"]))
        if st.button("Save rules"):
            common.update_settings(
                {
                    "lookback_high": lookback, "vol_window": vol_window, "sma_fast": sma_fast,
                    "sma_slow": sma_slow, "vol_mult": vol_mult, "cooldown": cooldown,
                }
            )
            st.cache_data.clear()
            st.success("Saved.")
            st.rerun()

# ---------------------------------------------------------------------------
# Tab 4 — Alerts
# ---------------------------------------------------------------------------
with tab4:
    st.subheader("Get notified")
    st.caption("Credentials are stored locally in ai_infra.db, next to this app — nowhere else, no cloud account needed.")

    with st.form("alert_form"):
        col1, col2 = st.columns(2)
        smtp_host = col1.text_input("SMTP server", value=settings.get("smtp_host", ""), placeholder="smtp.gmail.com")
        smtp_port = col2.number_input("Port", value=int(settings.get("smtp_port", 587) or 587))
        smtp_user = col1.text_input("Your email address", value=settings.get("smtp_user", ""))
        smtp_pass = col2.text_input(
            "App password", value=settings.get("smtp_pass", ""), type="password",
            help="Not your normal password — see README.md for how to create a Gmail app password.",
        )
        alert_to = st.text_area(
            "Send alerts to (comma-separated)", value=settings.get("alert_to", ""),
            placeholder="you@gmail.com, 5551234567@vtext.com",
        )
        interval = st.select_slider(
            "Check the market every…", options=[1, 2, 4, 6, 12],
            value=int(settings.get("scan_interval_hours", 2)) if int(settings.get("scan_interval_hours", 2)) in [1, 2, 4, 6, 12] else 2,
            format_func=lambda h: f"{h} hour(s)",
        )
        idea_threshold = st.slider(
            "Alert me when a Wave Score reaches…", 50, 95,
            int(settings.get("idea_alert_threshold", 75)),
            help="Ideas at or above this score trigger an email/text (at most once per name every 5 days).",
        )
        save_clicked = st.form_submit_button("💾 Save settings")

    if save_clicked:
        common.update_settings(
            {
                "smtp_host": smtp_host, "smtp_port": smtp_port, "smtp_user": smtp_user,
                "smtp_pass": smtp_pass, "alert_to": alert_to, "scan_interval_hours": interval,
                "idea_alert_threshold": idea_threshold,
            }
        )
        st.success("Saved.")
        st.rerun()

    st.markdown("**Turn a phone number into a text address**")
    c1, c2, c3 = st.columns([2, 2, 1])
    phone = c1.text_input("Phone number", placeholder="5551234567", label_visibility="collapsed")
    carrier = c2.selectbox("Carrier", list(common.CARRIER_GATEWAYS.keys()), label_visibility="collapsed")
    if c3.button("Add to list"):
        digits = "".join(ch for ch in phone if ch.isdigit())
        if digits:
            new_addr = f"{digits}@{common.CARRIER_GATEWAYS[carrier]}"
            merged = ", ".join(filter(None, [settings.get("alert_to", "").strip(), new_addr]))
            common.update_settings({"alert_to": merged})
            st.success(f"Added {new_addr}")
            st.rerun()

    st.divider()
    if st.button("✉️ Send a test alert"):
        ok, msg = common.send_alert(
            [{"symbol": "TEST", "sector": "Test", "date": datetime.now().date().isoformat(), "close": 0.0}],
            common.get_settings(),
        )
        (st.success if ok else st.error)(msg)

    st.divider()
    st.subheader("Background checking")
    st.caption("Runs quietly on your laptop's own scheduler and texts/emails you — no need to keep this tab open.")

    is_on = common.scheduler_status()
    colx, coly = st.columns([3, 1])
    colx.write("Status: " + ("🟢 Running in the background" if is_on else "⚪ Off — only checks while this page is open"))

    if is_on:
        if coly.button("Turn off"):
            common.disable_scheduler()
            st.rerun()
    else:
        if coly.button("Turn on"):
            try:
                common.enable_scheduler(int(settings.get("scan_interval_hours", 2)))
                st.success("Enabled — see README.md if it doesn't seem to run (macOS sometimes needs a one-time permission grant).")
            except Exception as e:
                st.error(f"Couldn't set this up automatically ({e}). See README.md for the two-line manual version.")
            st.rerun()

# ---------------------------------------------------------------------------
# Tab 5 — History
# ---------------------------------------------------------------------------
with tab5:
    st.subheader("Idea history")
    st.caption("Every day's ranked ideas are logged — this is the scorer's paper trail, and eventually its report card.")

    conn = common.get_conn()
    idea_df = pd.read_sql("SELECT * FROM idea_log ORDER BY run_date DESC, wave_score DESC", conn)
    if idea_df.empty:
        st.info("No idea history yet — it fills in as the radar runs.")
    else:
        st.dataframe(
            idea_df[["run_date", "symbol", "theme", "wave_score", "momentum", "sentiment", "fundamentals", "close"]]
            .rename(columns={"run_date": "Date", "symbol": "Ticker", "theme": "Theme", "wave_score": "Wave",
                             "momentum": "Price", "sentiment": "Crowd", "fundamentals": "Fundamentals",
                             "close": "Close"}),
            hide_index=True, width="stretch", height=300,
        )

    st.divider()
    st.subheader("Breakout signal history")
    st.caption("Every check — from this dashboard or the background scanner — adds to this log. This is what eventually tells you whether the rules are any good.")

    log_df = pd.read_sql("SELECT * FROM signal_log ORDER BY run_date DESC", conn)
    conn.close()

    if log_df.empty:
        st.info("No history yet — this fills in as the app (or the background checker) runs over time.")
    else:
        fired_df = log_df[log_df["fired"] == 1]
        st.metric("Breakout events logged", len(fired_df))
        if not fired_df.empty:
            st.bar_chart(fired_df.groupby("run_date").size(), height=200)
            st.dataframe(
                fired_df[["run_date", "symbol", "sector", "price_date", "close"]].rename(
                    columns={"run_date": "Logged", "symbol": "Ticker", "sector": "Sector",
                             "price_date": "Price date", "close": "Price"}
                ),
                hide_index=True, width="stretch",
            )

st.divider()
st.caption("Mechanical, rules-based research tool — not investment advice. Data via Yahoo Finance, refreshed every 30 minutes.")
