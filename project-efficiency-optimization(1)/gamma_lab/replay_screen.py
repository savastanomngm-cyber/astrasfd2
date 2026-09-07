import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from gamma_lab.models import known_rows, session_id
from gamma_lab.options import snapshot, concentration, scenario_surface
from gamma_lab.orderflow import classify, bars, footprint, quote_book, ofi
from gamma_lab.visuals import show, theme, price_chart, concentration_chart, BLUE


@st.cache_data(show_spinner=False, max_entries=8)
def flow_data(market, max_age_ms=2000):
    return classify(market, max_age_ms), quote_book(market)


def cursor_control(market):
    days = sorted(session_id(market.available_at).unique())
    day = st.selectbox("Replay session · Chicago trading date", days, key="replay_day")
    selected = market[session_id(market.available_at).eq(day)]
    start, end = selected.available_at.min().ceil("min"), selected.available_at.max().floor("min")
    if end <= start:
        cursor = selected.available_at.max()
    else:
        cursor = pd.Timestamp(st.slider("Information available through · UTC", min_value=start.to_pydatetime(), max_value=end.to_pydatetime(), value=end.to_pydatetime(), step=pd.Timedelta(minutes=1).to_pytimedelta(), format="HH:mm", key=f"cursor_{day}"))
    st.caption(f"Replay clock: {cursor.isoformat()} · Only events and snapshots available by this instant are eligible.")
    return cursor, day


def replay_screen(market, options, complete_quotes):
    st.caption("SYNCHRONIZED REPLAY")
    st.title("Location. Response. Decision.")
    st.write("Inspect the auction without borrowing information from the future.")
    cursor, day = cursor_control(market)
    trades, book = flow_data(known_rows(market, cursor))
    if trades.empty:
        st.info("No executed trades are available at this cursor. Quote-only inputs cannot produce a footprint.")
        return
    trades = trades[trades.session.eq(day)]
    candles = bars(trades, cursor=cursor)
    if candles.empty:
        st.info("No executed trades are available at this cursor.")
        return
    chain, quality = snapshot(options, cursor)
    weights = concentration(chain)
    zone = weights.groupby("strike").gamma_dollars_1pct.sum().idxmax() if not weights.empty else None
    a, b, c, d = st.columns(4)
    a.metric("Last observed trade", f"{trades.price.iloc[-1]:,.2f}")
    total = trades['size'].sum()
    b.metric("Executed volume", f"{total:,.0f}")
    c.metric("Classified volume", f"{trades.loc[trades.side.ne('unknown'), 'size'].sum() / total:.1%}" if total else "—")
    d.metric("Usable options", f"{quality['usable']} / {quality['available']}")
    show(price_chart(candles, zone))
    st.caption("Receipt-time 60-second bars. The current partial bar is visible for inspection but is not eligible for strategy signals. The concentration line is the snapshot at the cursor, not a historical signal overlay.")
    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("Footprint · last 60 seconds")
        recent = trades[trades.available_at > cursor - pd.Timedelta(seconds=60)]
        st.dataframe(footprint(recent), hide_index=True, width="stretch", height=350)
        st.caption("Unknown volume is retained. Delta is executed buy volume minus executed sell volume.")
    with right:
        st.subheader("Quote & classification audit")
        st.dataframe(trades.groupby(["side", "provenance"], as_index=False)['size'].sum().rename(columns={"size": "volume"}), hide_index=True, width="stretch")
        if book.empty:
            st.warning("No execution book: trade-only inputs can support a footprint, but cannot produce simulated fills.")
        else:
            q = book.iloc[-1]
            st.write(f"Last book: {q.bid:,.2f} bid / {q.ask:,.2f} ask")
            st.caption(f"Bid age {(cursor - q.bid_ts).total_seconds():.1f}s · Ask age {(cursor - q.ask_ts).total_seconds():.1f}s. The engine independently enforces the configured age limit.")
        with st.expander("Top-of-book order-flow imbalance"):
            try:
                updates = ofi(book, complete_updates=complete_quotes)
                updates = updates[updates.session.eq(day)]
                fig = go.Figure(go.Scatter(x=updates.available_at, y=updates.ofi.cumsum(), mode="lines", line_color=BLUE, name="Cumulative OFI"))
                show(theme(fig, 260))
                st.caption("Displayed-supply changes, not executed delta. Diagnostic only; OFI is not a tested strategy variant in this release.")
            except ValueError as error:
                st.info(str(error))


def options_screen(market, options):
    st.caption("OPTIONS MAP")
    st.title("Concentration, not certainty.")
    st.write("Separate observable open interest from gamma modeling and dealer-position assumptions.")
    cursor, _ = cursor_control(market)
    if options.empty:
        st.info("Import matching options snapshots to enable this screen. Futures prices alone cannot supply options exposure.")
        return
    max_age = st.select_slider("Maximum options quote age", options=[60, 300, 900, 1800], value=900, format_func=lambda x: f"{x // 60} min")
    chain, quality = snapshot(options, cursor, max_age_s=max_age)
    a, b, c = st.columns(3)
    a.metric("Available contracts", str(quality["available"]))
    b.metric("Usable contracts", str(quality["usable"]))
    c.metric("Coverage", f"{quality['usable'] / quality['available']:.0%}" if quality["available"] else "—")
    st.caption("Coverage is usable contracts divided by observed available contracts, not verified coverage of the entire exchange chain.")
    with st.expander("Exclusion reasons", expanded=chain.empty):
        st.json(quality["excluded"])
    if chain.empty:
        st.warning("No usable point-in-time chain. Review quote age, exercise style, expiry, and OI availability.")
        return
    expiries = sorted(chain.expiry.astype(str).unique())
    chosen = st.multiselect("Expiration filter · UTC", expiries, default=expiries)
    chain = chain[chain.expiry.astype(str).isin(chosen)]
    if chain.empty:
        st.info("Select at least one expiration.")
        return
    show(concentration_chart(concentration(chain)))
    st.caption("Gross, unsigned CME-options-only concentration. Long calls and long puts both have positive gamma; this does not identify dealer inventory. Greeks use each snapshot's futures price.")
    st.subheader("Wall reliability")
    columns = ["strike", "right", "expiry", "oi", "iv", "gamma", "gamma_dollars_1pct", "quote_age_s", "oi_age_hours", "bid", "ask", "option_id"]
    st.dataframe(chain[columns].sort_values(["strike", "right"]), hide_index=True, width="stretch")
    with st.expander("Signed-gamma scenarios · assumptions, not observations"):
        scenario = st.selectbox("Assumed dealer positioning", ["All dealer long", "All dealer short", "Calls long / puts short"])
        shift = st.slider("Parallel IV shift · percentage points", -5.0, 5.0, 0.0, .5)
        center = float(chain.future_price.median())
        surface = scenario_surface(chain, np.linspace(center * .985, center * 1.015, 61), scenario, shift / 100)
        fig = go.Figure(go.Scatter(x=surface.future_price, y=surface.assumed_gamma_dollars_1pct, line_color=BLUE, name="Assumed signed gamma"))
        show(theme(fig, 300))
        st.caption("A scenario is not an estimated probability. No total-market dealer gamma or gamma-flip claim is made.")
