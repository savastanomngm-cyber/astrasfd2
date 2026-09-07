import numpy as np
import pandas as pd
from scipy.stats import norm


def session_returns(path, capital):
    if path.empty:
        return pd.Series(dtype=float)
    equity = path.groupby("session", sort=True).equity.last()
    previous = equity.shift(1).fillna(capital)
    return (equity - previous) / previous


def summarize(result, capital):
    path, trades = result["equity"], result["trades"]
    if path.empty:
        return {"closed_trades": 0, "sessions": 0, "status": result["status"]}
    r = session_returns(path, capital)
    wealth = np.r_[capital, path.equity.to_numpy()]
    peak = np.maximum.accumulate(wealth)
    dd = wealth / peak - 1
    valid_sharpe = len(r) >= 20 and r.std() > 0
    return {"closed_trades": len(trades), "sessions": len(r), "net_pnl_marked": float(wealth[-1] - capital), "expectancy_closed_trade": float(trades.net_pnl.mean()) if len(trades) else None, "max_drawdown_pct": float(dd.min() * 100), "annualized_session_sharpe": float(r.mean() / r.std() * np.sqrt(252)) if valid_sharpe else None, "open_position": result["open_position"] is not None, "status": result["status"]}


def block_interval(returns, repeats=1000, block=5, seed=42):
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    if n < max(20, block * 4):
        return {"status": "Insufficient sessions (minimum 20)", "low": None, "high": None}
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(repeats):
        starts = rng.integers(0, n - block + 1, size=int(np.ceil(n / block)))
        sample = np.concatenate([values[s:s+block] for s in starts])[:n]
        means.append(sample.mean())
    low, high = np.quantile(means, [.025, .975])
    return {"status": "95% moving-session-block interval for mean session return", "low": float(low), "high": float(high), "block_sessions": block}


def deflated_sharpe(sharpe_per_session, n_obs, effective_trials, trial_sharpe_std=None, skew=0., kurtosis=3.):
    if n_obs < 20 or effective_trials < 1 or kurtosis < 1 or not all(np.isfinite(v) for v in [sharpe_per_session, n_obs, effective_trials, skew, kurtosis]):
        return {"status": "Invalid or insufficient inputs"}
    if effective_trials > 1 and (trial_sharpe_std is None or not np.isfinite(trial_sharpe_std) or trial_sharpe_std <= 0):
        return {"status": "Trial Sharpe dispersion required; no verdict"}
    expected = 0.
    if effective_trials > 1:
        euler = np.euler_gamma
        expected = trial_sharpe_std * ((1-euler) * norm.ppf(1-1/effective_trials) + euler * norm.ppf(1-1/(effective_trials * np.e)))
    variance = 1 - skew * sharpe_per_session + (kurtosis-1) / 4 * sharpe_per_session ** 2
    if variance <= 0:
        return {"status": "Invalid moment-adjusted variance"}
    probability = norm.cdf((sharpe_per_session - expected) * np.sqrt(n_obs-1) / np.sqrt(variance))
    return {"status": "Diagnostic only; session autocorrelation is not corrected by this formula", "probability": float(probability), "benchmark_per_session": float(expected)}
