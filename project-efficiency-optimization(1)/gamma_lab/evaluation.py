from dataclasses import asdict, replace

import pandas as pd

from gamma_lab.models import session_id
from gamma_lab.orderflow import classify, bars, quote_book
from gamma_lab.setups import add_locations
from gamma_lab.research import walk_forward
from gamma_lab.execution import simulate
from gamma_lab.statistics import summarize


def prepare(market, options, quote_age_ms=2000):
    trades = classify(market, max_age_ms=quote_age_ms)
    if trades.empty:
        raise ValueError("Executed trades are required for evaluation.")
    candles = bars(trades, cursor=market.available_at.max())
    return add_locations(candles, options), quote_book(market)


def run_experiment(store, study, candles, book, cfg, train_sessions=3, holdout=False):
    cfg.validate()
    manifest = {"phase": "holdout" if holdout else "walk-forward", "study_id": study["id"], "source_ids": study["sources"], "contract": study["contract"], "holdout_sessions": study["holdout"], "train_sessions": train_sessions, "config": asdict(cfg), "holdout_previously_exposed": bool(study["previously_exposed"] or study["opened_at"])}
    run_id = store.register(manifest, {"status": "started"}, holdout=holdout)
    if holdout:
        store.open_holdout(study["id"])
    try:
        if sorted(candles.session.unique()) != study["sessions"]:
            raise ValueError("Some reserved sessions have no trade bars. Repair the data selection; the holdout split will not be silently changed.")
        result = walk_forward(candles, book, cfg, study["contract"], train_sessions=train_sessions, holdout_sessions=1, inspect_holdout=holdout,
            register_trial=lambda config, stats: store.register({**config, "parent_run": run_id, "source_ids": study["sources"]}, stats, holdout=holdout), complete_trial=store.complete_run)
        tables = {"summary": result["summary"], "folds": result["folds"]}
        for name, outcomes in result["results"].items():
            key = name.lower().replace(" + ", "_").replace(" ", "_")
            for table in ["trades", "orders", "equity", "signals"]:
                tables[f"{key}_{table}"] = outcomes[table]
        for name, frame in result["studies"].items():
            tables["study_" + name.lower().replace(" ", "_")] = frame
        store.save_artifacts(run_id, tables)
        store.complete_run(run_id, {"status": result["status"], "summary": result["summary"].to_dict("records"), "artifacts": list(tables)})
        return {**result, "run_id": run_id, "manifest": manifest}
    except Exception as error:
        store.complete_run(run_id, {"status": "failed", "error": str(error)})
        raise


def stress_experiment(store, evaluation, book, cfg, symbol):
    rows = []
    days = evaluation["folds"].session.unique() if not evaluation["folds"].empty else []
    quotes = book[session_id(book.available_at).isin(days)]
    for label, stressed in [("Base costs", cfg), ("2× fees + 1 tick", replace(cfg, fee_per_side=cfg.fee_per_side * 2, slippage_ticks=cfg.slippage_ticks + 1)), ("+750 ms latency", replace(cfg, latency_ms=cfg.latency_ms + 750))]:
        for variant, outcome in evaluation["results"].items():
            config = {"phase": "stress", "parent_run": evaluation["run_id"], "scenario": label, "variant": variant, "config": asdict(stressed)}
            run_id = store.register(config, {"status": "started"}, holdout=evaluation["manifest"]["phase"] == "holdout")
            try:
                result = simulate(quotes, outcome["signals"], stressed, symbol)
                stats = summarize(result, cfg.capital)
                store.complete_run(run_id, stats)
                rows.append({"scenario": label, "variant": variant, **stats})
            except Exception as error:
                store.complete_run(run_id, {"status": "failed", "error": str(error)})
                raise
    return pd.DataFrame(rows)
