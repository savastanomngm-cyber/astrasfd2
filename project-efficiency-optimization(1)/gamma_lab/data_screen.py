import pandas as pd
import streamlit as st

from gamma_lab.importers import canonical, ninjatrader, databento_trades, template
from gamma_lab.tutorial import tutorial


@st.dialog("Import a permitted dataset", width="large")
def import_dialog(store):
    st.write("Files stay on the machine running this terminal. No data-provider account or automatic download is used.")
    with st.form("import_data"):
        adapter = st.selectbox("File format", ["Canonical CSV / Parquet", "NinjaTrader tick text", "Databento trades CSV"])
        kind = st.selectbox("Dataset", ["market", "options"])
        symbol = st.text_input("Resolved futures contract", "ESU6", help="Used by NinjaTrader and Databento; canonical files carry their own contract field.")
        timezone = st.text_input("Timezone for naive canonical timestamps", "UTC")
        nt_kind = st.selectbox("NinjaTrader stream", ["Last", "Bid", "Ask"])
        file = st.file_uploader("Source file", type=["csv", "parquet", "txt"])
        name = st.text_input("Source label", placeholder="e.g. ES September · licensed tick export")
        synthetic = st.checkbox("This file contains synthetic / test data")
        full_quotes = st.checkbox("I attest this contains every top-of-book update with displayed sizes", help="Required for OFI. Trade-associated snapshots do not qualify.")
        permitted = st.checkbox("I have permission to use and store this dataset")
        submit = st.form_submit_button("Validate & import", type="primary")
    if submit:
        if file is None or not permitted:
            st.error("Choose a file and confirm your data-use permission.")
            return
        try:
            raw = file.getvalue()
            if len(raw) > 100 * 1024 * 1024:
                raise ValueError("Maximum upload size is 100 MB.")
            if adapter != "Canonical CSV / Parquet" and kind != "market":
                raise ValueError("Options must use the canonical schema with explicit OI publication timestamps.")
            if adapter == "NinjaTrader tick text":
                frame = ninjatrader(raw, symbol, nt_kind)
            elif adapter == "Databento trades CSV":
                frame = databento_trades(raw, symbol)
            else:
                frame = canonical(raw, file.name, kind, timezone, "event")
            if len(frame) > 2_000_000:
                raise ValueError("Limit each import to 2 million records.")
            source_id = store.add(raw, frame, kind, {"label": name.strip() or file.name, "filename": file.name, "adapter": adapter, "timezone": timezone, "synthetic": synthetic, "complete_quotes": full_quotes, "permission_attested": True})
            selected = list(st.session_state.get("source_ids", []))
            st.session_state["pending_source_ids"] = list(dict.fromkeys(selected + [source_id]))
            st.session_state.pop("evaluation", None)
            st.rerun()
        except Exception as error:
            st.error(f"Import rejected: {error}")


def load_tutorial(store, symbol):
    market, options = tutorial(symbol, sessions=6)
    ids = []
    for kind, frame in [("market", market), ("options", options)]:
        raw = frame.to_csv(index=False).encode()
        ids.append(store.add(raw, frame, kind, {"label": f"Tutorial · {symbol} · {kind}", "synthetic": True, "generator": "seeded-v1", "complete_quotes": kind == "market", "permission_attested": True}))
    st.session_state["pending_source_ids"] = ids
    st.session_state.pop("evaluation", None)
    st.rerun()


def data_screen(store, sources, market, options, study):
    st.caption("DATA WORKSPACE")
    st.title("Good research starts with good data.")
    st.write("Audit your inputs before testing a hypothesis. Every result should have a traceable source.")
    left, right = st.columns([1, 1])
    with left:
        if st.button("Import dataset", type="primary", width="stretch"):
            import_dialog(store)
    with right:
        with st.popover("Explore with synthetic data", width="stretch"):
            st.write("A deterministic, six-session tutorial. These are invented prices, not exchange history or evidence of an edge.")
            symbol = st.selectbox("Tutorial contract", ["ESU6", "NQU6"])
            if st.button("Load synthetic tutorial", type="primary"):
                with st.spinner("Generating and validating tutorial files…"):
                    load_tutorial(store, symbol)
    st.divider()
    if market.empty:
        st.html('''<div class="empty-panel"><div class="eyebrow">Your workspace is ready</div><h3>No market data loaded. No invented results.</h3><p>Start with an entitled tick export, or load the clearly labeled tutorial to explore the workflow. OHLC bars cannot reconstruct a genuine footprint.</p><div class="pipeline"><span>Source files</span>→<span>Data audit</span>→<span>Causal replay</span>→<span>Evaluation</span></div></div>''')
        a, b, c = st.columns(3)
        with a:
            st.subheader("Futures ticks")
            st.write("Individual ES / NQ contracts. Trades with aggressor flags or usable historical quotes.")
        with b:
            st.subheader("Options snapshots")
            st.write("Explicit expirations, quote availability, and open-interest publication times.")
        with c:
            st.subheader("Local by design")
            st.write("Immutable source files, Parquet partitions, DuckDB queries, and a SQLite trial registry.")
    else:
        trades = market[market.kind.eq("trade")]
        a, b, c, d = st.columns(4)
        a.metric("Trade records", f"{len(trades):,}")
        b.metric("Quote events", f"{market.kind.ne('trade').sum():,}")
        c.metric("Options snapshots", f"{len(options):,}")
        d.metric("Final session", "Opened" if study and study["opened_at"] else "Reserved")
        st.subheader("Source audit")
        selected = set(st.session_state.get("source_ids", []))
        rows = [{"Source": s.get("label", s["id"][:12]), "Stream": s["kind"], "Data": "SYNTHETIC" if s.get("synthetic") else "Imported", **s["audit"]} for s in sources if s["id"] in selected]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("Gaps are review flags, not a verified holiday calendar. Sessions use the 17:00 America/Chicago boundary; no continuous-contract stitching or automatic holiday/roll assumptions.")
        with st.expander("Source provenance & immutable hashes"):
            for source in sources:
                if source["id"] in selected:
                    st.json(source)
    st.divider()
    st.subheader("Supported input contracts")
    st.write("Canonical files use event timestamps, explicit contract identifiers, and decimal prices. Availability cannot precede the event; unknown aggressors remain unknown.")
    a, b = st.columns(2)
    a.download_button("Download futures CSV header", template("market"), "market-template.csv", "text/csv", width="stretch")
    b.download_button("Download options CSV header", template("options"), "options-template.csv", "text/csv", width="stretch")
    with st.expander("Import conventions & limitations"):
        st.markdown("""- **Canonical CSV / Parquet:** timezone-aware timestamps recommended. Naive timestamps require the correct IANA timezone; ambiguous DST times are rejected. `kind` is `trade`, `quote`, `bid`, or `ask`. Quote rows still require `price` and `size` (use a valid midpoint and zero).
- **NinjaTrader:** supported tick text only, with UTC export timestamps. Three fields for Last/Bid/Ask, or five-field Last tick-replay records. Market Replay binary files and bars are not supported. Bid/Ask export volume is not treated as displayed depth.
- **Databento:** a single resolved instrument, trades-schema CSV with pretty timestamps and decimal prices. No automatic downloads, DBN or options adapter.
- **Options:** `right` is C/P; `style` is European/American. American contracts are audited but excluded from Black-76 analytics. OI is unusable until its explicit publication time.
- **Limits:** 100 MB / two million records per import. Overlapping exports for the same contract and stream are rejected, not silently deduplicated.""")
