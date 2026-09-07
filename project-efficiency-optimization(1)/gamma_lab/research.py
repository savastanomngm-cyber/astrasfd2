from dataclasses import asdict, replace
import pandas as pd

from gamma_lab.execution import simulate
from gamma_lab.models import session_id
from gamma_lab.setups import VARIANTS, signals, encounters
from gamma_lab.statistics import summarize, session_returns, block_interval


def walk_forward(bars, book, cfg, symbol, train_sessions=3, holdout_sessions=1, inspect_holdout=False, register_trial=None, complete_trial=None):
    if train_sessions < 1 or holdout_sessions < 1:
        raise ValueError("Training and holdout session counts must be positive.")
    if bars.empty:
        return {"status": "No completed bars", "folds": pd.DataFrame(), "summary": pd.DataFrame(), "results": {}, "studies": {}}
    days = sorted(bars.session.unique())
    minimum = train_sessions + holdout_sessions + 1
    if len(days) < minimum:
        return {"status": f"Need at least {minimum} sessions; received {len(days)}", "folds": pd.DataFrame(), "summary": pd.DataFrame(), "results": {}, "studies": {}}
    if book.empty:
        return {"status": "Execution quotes required", "folds": pd.DataFrame(), "summary": pd.DataFrame(), "results": {}, "studies": {}}
    final_days = days[-holdout_sessions:]
    development = days[:-holdout_sessions]
    quote_sessions = session_id(book.available_at)
    folds, results, summaries, studies = [], {}, [], {}
    visible_days = days if inspect_holdout else development
    visible_bars = bars[bars.session.isin(visible_days)]
    for variant in VARIANTS:
        if variant in ["Gamma location", "Gamma + footprint"] and not visible_bars.gamma_zone.notna().any():
            summaries.append({"variant": variant, "status": "Blocked: no point-in-time gamma coverage"})
            continue
        collected = []
        test_days = final_days if inspect_holdout else development[train_sessions:]
        for day in test_days:
            day_index = days.index(day)
            # Final holdout never becomes training data, even when it spans several sessions.
            prior_days = development[-train_sessions:] if inspect_holdout else days[max(0, day_index-train_sessions):day_index]
            train = bars[bars.session.isin(prior_days)].copy().reset_index(drop=True)
            train_book = book[quote_sessions.isin(prior_days)]
            scores = []
            for threshold in [.20, .35]:
                trial_cfg = replace(cfg, delta_threshold=threshold)
                candidate = signals(train, trial_cfg, variant)
                if not candidate.empty:
                    session_ends = train.groupby("session").ts.max()
                    # Purge entries whose planned outcome window reaches the training boundary.
                    cutoff = candidate.session.map(session_ends) - pd.Timedelta(minutes=cfg.hold_bars + 2)
                    candidate = candidate[candidate.ts < cutoff]
                trial_id = register_trial({"phase": "training", "variant": variant, "test_session": day, "train_sessions": prior_days, "config": asdict(trial_cfg)}, {"status": "started"}) if register_trial else None
                trial = simulate(train_book, candidate, trial_cfg, symbol)
                stats = summarize(trial, cfg.capital)
                score = stats.get("net_pnl_marked", float("-inf")) if not trial["open_position"] and stats.get("closed_trades", 0) else float("-inf")
                scores.append((score, threshold))
                if complete_trial and trial_id:
                    complete_trial(trial_id, stats)
            score, threshold = max(scores, key=lambda x: x[0])
            eligible = score != float("-inf")
            history = bars[bars.session.isin(prior_days + [day])].copy().reset_index(drop=True)
            chosen = signals(history, replace(cfg, delta_threshold=threshold), variant)
            chosen = chosen[chosen.session.eq(day)] if eligible else chosen.iloc[:0]
            collected.append(chosen)
            folds.append(dict(variant=variant, session=day, threshold=threshold, signals=len(chosen), training_status="selected on training only" if eligible else "no usable training trades; no test entries", holdout=inspect_holdout))
        all_signals = pd.concat(collected, ignore_index=True) if collected else signals(bars.iloc[:0], cfg, variant)
        eval_book = book[quote_sessions.isin(test_days)]
        result = simulate(eval_book, all_signals, cfg, symbol)
        result["signals"] = all_signals
        results[variant] = result
        stats = summarize(result, cfg.capital)
        interval = block_interval(session_returns(result["equity"], cfg.capital))
        summaries.append({"variant": variant, **stats, "mean_return_ci_low": interval.get("low"), "mean_return_ci_high": interval.get("high"), "uncertainty": interval["status"]})
        if not result["equity"].empty:
            daily = result["equity"].groupby("session").equity.last()
            previous = daily.shift(1).fillna(cfg.capital)
            pnl = (daily - previous).to_dict()
            for fold in folds:
                if fold["variant"] == variant:
                    fold["marked_session_pnl"] = pnl.get(fold["session"], 0.)
    study_bars = bars[bars.session.isin(final_days if inspect_holdout else development)].reset_index(drop=True)
    for label, col in [("Gamma", "gamma_zone"), ("Round numbers", "round_zone"), ("Prior session close", "prior_close_zone"), ("Offset placebo", "placebo_zone")]:
        studies[label] = encounters(study_bars, col, cfg.hold_bars, max(cfg.cooldown_bars, cfg.hold_bars))
    return {"status": "Exploratory only; compare opportunity counts and coverage. Offset placebo is not a fully matched causal control.", "folds": pd.DataFrame(folds), "summary": pd.DataFrame(summaries), "results": results, "studies": studies, "holdout_sessions": final_days, "holdout_opened": inspect_holdout}
