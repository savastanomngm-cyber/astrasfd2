from dataclasses import asdict
import io
import json
import zipfile

import pandas as pd
import streamlit as st

from gamma_lab.evaluation import prepare, run_experiment, stress_experiment
from gamma_lab.execution import size_contracts
from gamma_lab.models import RunConfig, contract, digest
from gamma_lab.statistics import session_returns, deflated_sharpe
from gamma_lab.visuals import show, equity_chart

cached_prepare = st.cache_data(show_spinner=False, max_entries=4)(prepare)


def config_form():
    with st.expander("Execution & hypothesis settings", expanded=True):
        a, b, c, d = st.columns(4)
        capital = a.number_input("Starting capital · USD", min_value=1000., max_value=10000000., value=25000., step=1000.)
        risk = b.number_input("Risk per trade · %", min_value=.01, max_value=5., value=1., step=.1)
        fee = c.number_input("Fee / side / contract · USD", min_value=0., max_value=100., value=2.5, step=.25)
        slippage = d.number_input("Slippage · ticks / side", min_value=0, max_value=100, value=1)
        a, b, c, d = st.columns(4)
        latency = a.number_input("Order latency · ms", min_value=0, max_value=10000, value=250, step=50)
        age = b.number_input("Maximum quote age · ms", min_value=100, max_value=30000, value=2000, step=100)
        stop = c.number_input("Stop distance · ticks", min_value=1, max_value=1000, value=12)
        target = d.number_input("Target distance · ticks", min_value=1, max_value=2000, value=20)
        a, b, c, d = st.columns(4)
        hold = a.number_input("Maximum hold · minutes", min_value=1, max_value=120, value=5)
        qty = b.number_input("Maximum contracts", min_value=1, max_value=20, value=1)
        loss = c.number_input("Session loss halt · USD", min_value=1., max_value=100000., value=500., step=50.)
        train = d.number_input("Rolling training sessions", min_value=1, max_value=60, value=3)
        st.caption("Fixed hypotheses: price baseline, gamma location, footprint, and gamma + footprint. Training-only delta grid: 0.20 / 0.35. Zone tolerance: 8 ticks; minimum classified volume: 80%; cooldown: 5 bars. The last session is always reserved.")
    return RunConfig(capital=capital, risk_fraction=risk / 100, fee_per_side=fee, slippage_ticks=slippage, latency_ms=latency, quote_age_ms=age, stop_ticks=stop, target_ticks=target, hold_bars=hold, max_contracts=qty, session_loss=loss), int(train)


def research_screen(store, study, market, options):
    st.caption("RESEARCH / WALK-FORWARD")
    st.title("Test the contribution, not the story.")
    st.write("Compare components under the same execution assumptions. No promise of profitability.")
    cfg, train = config_form()
    qty = size_contracts(cfg.capital, cfg, contract(study["contract"]))
    if qty == 0:
        st.warning("The integer risk cap permits zero contracts at these settings. The engine will not force a trade.")
    unopened = not study["opened_at"] and not study["previously_exposed"]
    st.info(f"Final session {study['holdout'][0]} · {'not opened in this registry' if unopened else 'previously exposed; any further evaluation is exploratory'}. This cannot verify whether the data was examined outside this application.")
    minimum = train + 2
    insufficient = len(study["sessions"]) < minimum
    if insufficient:
        st.warning(f"Need at least {minimum} sessions for this split; {len(study['sessions'])} available.")
    a, b = st.columns(2)
    development = a.button("Run walk-forward comparison", type="primary", disabled=insufficient, width="stretch")
    consent = st.checkbox("I understand opening the holdout permanently marks it as exposed")
    opened = b.button("Evaluate final holdout", disabled=insufficient or not consent, width="stretch")
    fingerprint = digest({"study": study["id"], "config": asdict(cfg), "train": train})
    if development or opened:
        try:
            with st.spinner("Building causal features and registering every tuning trial…"):
                candles, book = cached_prepare(market, options, cfg.quote_age_ms)
                result = run_experiment(store, study, candles, book, cfg, train, holdout=opened)
                st.session_state["evaluation"] = {"fingerprint": fingerprint, "result": result, "config": cfg}
                st.session_state.pop("stress", None)
            st.rerun()
        except Exception as error:
            st.error(f"Evaluation stopped: {error}")
    saved = st.session_state.get("evaluation")
    if not saved or saved["fingerprint"] != fingerprint:
        st.html('<div class="empty-panel"><h3>A comparison, not a leaderboard.</h3><p>Run the registered hypotheses to inspect out-of-sample P&amp;L, drawdown, opportunity counts, and uncertainty. Changing settings does not overwrite a previous run.</p></div>')
        return
    result = saved["result"]
    st.divider()
    st.subheader("Out-of-sample comparison")
    st.caption(f"Run {result['run_id']} · {'FINAL HOLDOUT — NOW EXPOSED' if result['manifest']['phase'] == 'holdout' else 'DEVELOPMENT WALK-FORWARD'} · source and configuration hashes saved")
    st.write(result["status"])
    if result["summary"].empty:
        return
    if result["results"]:
        show(equity_chart(result["results"], cfg.capital))
    st.dataframe(result["summary"], hide_index=True, width="stretch")
    st.caption("Marked P&L includes unclosed positions; closed-trade expectancy does not. Stops may slip. Mean-return intervals require at least 20 sessions and use moving session blocks, not independent ticks.")
    with st.expander("Fold decisions & training selections"):
        st.dataframe(result["folds"], hide_index=True, width="stretch")
    with st.expander("All eligible zone encounters · event study"):
        label = st.selectbox("Location control", list(result["studies"]))
        frame = result["studies"][label]
        st.write(f"{len(frame):,} eligible encounters")
        st.dataframe(frame, hide_index=True, width="stretch")
        st.caption("Descriptive forward outcomes, not executable trade returns. Offset placebo is not a fully matched control; gamma and round-number effects can overlap. ES and NQ are not independent confirmations.")
    with st.expander("Cost & latency stress · fixed out-of-sample signals"):
        st.write("Replays the same signals. No retuning. Risk-based integer sizing is recalculated under each cost scenario.")
        if st.button("Run execution stress scenarios"):
            try:
                with st.spinner("Registering and replaying stress scenarios…"):
                    _, book = cached_prepare(market, options, cfg.quote_age_ms)
                    st.session_state["stress"] = stress_experiment(store, result, book, cfg, study["contract"])
            except Exception as error:
                st.error(str(error))
        if "stress" in st.session_state:
            st.dataframe(st.session_state["stress"], hide_index=True, width="stretch")
    with st.expander("Deflated Sharpe · diagnostic only"):
        if result["results"]:
            variant = st.selectbox("Variant for diagnostic", list(result["results"]))
            returns = session_returns(result["results"][variant]["equity"], cfg.capital)
            if len(returns) < 20 or returns.std() <= 0:
                st.info("At least 20 sessions with nonzero return variance are required; no diagnostic verdict.")
            else:
                effective = st.number_input("Assumed effective trial count", min_value=1, value=1)
                dispersion = st.number_input("Trial Sharpe dispersion · per-session scale", min_value=0., value=0., step=.001, format="%.4f")
                st.json(deflated_sharpe(float(returns.mean() / returns.std()), len(returns), effective, dispersion, float(returns.skew()), float(returns.kurtosis() + 3)))
                st.caption("Do not use annualized Sharpe dispersion here. Effective independent trials cannot be inferred from the raw trial count; session autocorrelation is not corrected by this formula.")


def archive_run(store, run_id, row):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(row, default=str, indent=2))
        for name, frame in store.artifacts(run_id).items():
            archive.writestr(f"{name}.csv", frame.to_csv(index=False))
    return output.getvalue()


def journal_screen(store):
    st.caption("TRADE JOURNAL / TRIAL REGISTRY")
    st.title("Every decision leaves a record.")
    st.write("Persistent local trials, exact signal times, simulated fills, and source references.")
    runs = store.runs()
    if runs.empty:
        st.info("No registered trials yet. Run a comparison in Research to create the first audit trail.")
        return
    records = []
    for row in runs.to_dict("records"):
        config, result = json.loads(row["config"]), json.loads(row["result"])
        records.append({"id": row["id"], "created": row["created"], "phase": config.get("phase"), "variant": config.get("variant", "All variants"), "status": result.get("status"), "holdout": bool(row["holdout"]), "config_hash": config.get("config_hash")})
    st.metric("Registered runs & trials", f"{len(records):,}")
    st.dataframe(pd.DataFrame(records), hide_index=True, width="stretch")
    chosen = st.selectbox("Inspect registered run", [r["id"] for r in records], format_func=lambda x: next(f"{r['id']} · {r['phase']} · {r['variant']}" for r in records if r["id"] == x))
    row = runs[runs.id.eq(chosen)].iloc[0].to_dict()
    tables = store.artifacts(chosen)
    if tables:
        name = st.selectbox("Saved table", sorted(tables), index=next((i for i, n in enumerate(sorted(tables)) if n.endswith("_trades")), 0))
        st.dataframe(tables[name], hide_index=True, width="stretch")
    else:
        st.caption("Training and stress trials store their configuration and summary. Parent evaluations also store fills, orders, equity, signals, and event studies.")
    with st.expander("Exact configuration & outcome"):
        st.json(json.loads(row["config"]))
        st.json(json.loads(row["result"]))
    st.download_button("Export audit bundle", archive_run(store, chosen, row), f"gamma-lab-{chosen}.zip", "application/zip")
