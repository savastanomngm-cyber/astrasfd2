import pandas as pd
import streamlit as st

from gamma_lab.data_screen import data_screen
from gamma_lab.models import session_id
from gamma_lab.replay_screen import replay_screen, options_screen
from gamma_lab.research_screen import research_screen, journal_screen
from gamma_lab.storage import Store, reject_overlapping_sources
from gamma_lab.visuals import inject_style

st.set_page_config(page_title="Gamma Lab · ES/NQ Research", layout="wide", initial_sidebar_state="expanded")
inject_style()
store = Store()
sources = store.sources()
source_map = {s["id"]: s for s in sources}
if "pending_source_ids" in st.session_state:
    st.session_state["source_ids"] = st.session_state.pop("pending_source_ids")

with st.sidebar:
    st.html('<div class="brand"><span class="brand-mark">Γ</span> Gamma Lab</div><div class="brand-sub">Order-flow research terminal</div>')
    st.divider()
    screen = st.radio("WORKSPACE", ["Data workspace", "Options map", "Synchronized replay", "Research", "Trade journal"], key="screen")
    st.divider()
    st.caption("DATA SELECTION")
    selected = st.multiselect("Source files", list(source_map), format_func=lambda x: source_map[x].get("label", x[:12]), key="source_ids", placeholder="Choose imported files")
    st.caption("Select matching futures and options files. Contracts are analyzed separately.")
    st.divider()
    st.caption("LOCAL-FIRST / RESEARCH ONLY")
    st.write("No live feed. No order routing.")
    st.caption("Parquet + DuckDB + SQLite")
    with st.expander("About this workspace"):
        st.write("Data is saved on the machine running Python, not in browser storage. The v0 sandbox is temporary; import original files into your own local copy for long-term use.")
        st.write("Get the source through the project's GitHub connection. This Streamlit app needs a persistent Python process and local disk; it is not a Vercel serverless deployment.")
        st.caption("No subscription or data download is initiated. Market-data entitlements remain your responsibility.")

st.html('<div class="workbench-bar"><span>RESEARCH WORKBENCH <span aria-hidden="true"> / </span> ES & NQ FUTURES</span><span class="mode-pill">Historical research · Local storage</span></div>')
market, options = pd.DataFrame(), pd.DataFrame()
study = None
complete_quotes = False
if selected:
    try:
        selected_sources = [source_map[s] for s in selected]
        modes = {bool(s.get("synthetic")) for s in selected_sources}
        if len(modes) > 1:
            raise ValueError("Do not mix synthetic and imported market datasets in the same study.")
        market_ids = [s["id"] for s in selected_sources if s["kind"] == "market"]
        option_ids = [s["id"] for s in selected_sources if s["kind"] == "options"]
        market, options = store.load(market_ids), store.load(option_ids)
        reject_overlapping_sources(market)
        reject_overlapping_sources(options)
        if not market.empty:
            symbol = st.sidebar.selectbox("Active contract", sorted(market.contract.unique()))
            market = market[market.contract.eq(symbol)].copy()
            if not options.empty:
                options = options[options.contract.eq(symbol)].copy()
            days = sorted(session_id(market.available_at).unique())
            study = store.study(selected, symbol, days)
            complete_quotes = all(s.get("complete_quotes", False) for s in selected_sources if s["kind"] == "market")
        if True in modes:
            st.warning("SYNTHETIC TUTORIAL — Generated prices and options. Not historical market data, not live prices, and not evidence of profitability.")
    except Exception as error:
        st.error(f"Source selection blocked: {error}")
        market, options, study = pd.DataFrame(), pd.DataFrame(), None

if screen == "Data workspace":
    data_screen(store, sources, market, options, study)
elif screen == "Trade journal":
    journal_screen(store)
elif market.empty or study is None:
    st.title(screen)
    st.info("Import a futures dataset or load the synthetic tutorial in Data workspace to begin. Missing inputs disable analyses rather than fabricate results.")
else:
    development_days = [d for d in study["sessions"] if d not in study["holdout"]]
    if screen == "Research":
        store.record_exposure(study["contract"], development_days)
        research_screen(store, study, market, options)
    else:
        visible_days = development_days
        if study["opened_at"]:
            visible_days = study["sessions"]
            st.caption("Final holdout was opened. Replay of that session is now exploratory.")
        else:
            st.caption(f"Final session {study['holdout'][0]} is hidden. Explicitly open it in Research to inspect it.")
        visible_market = market[session_id(market.available_at).isin(visible_days)]
        if visible_market.empty:
            st.info("No development session available. Import more sessions; the final session is reserved.")
        else:
            store.record_exposure(study["contract"], visible_days)
            if screen == "Options map":
                options_screen(visible_market, options)
            else:
                replay_screen(visible_market, options, complete_quotes)

st.divider()
st.caption("Gamma Lab / Historical research only. Data quality, model assumptions, and statistical evidence are separate questions. No live trading or profitability claims.")
