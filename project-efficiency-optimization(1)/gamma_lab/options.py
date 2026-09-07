import math

import numpy as np
import pandas as pd
import QuantLib as ql
from scipy.optimize import brentq

from gamma_lab.models import known_rows

YEAR_SECONDS = 365 * 24 * 3600


def black(future, strike, years, rate, iv, right="C"):
    if not all(np.isfinite(x) for x in [future, strike, years, rate, iv]) or min(future, strike, years, iv) <= 0 or right not in ["C", "P"]:
        raise ValueError("Positive finite futures price, strike, maturity and IV required.")
    payoff = ql.PlainVanillaPayoff(ql.Option.Call if right == "C" else ql.Option.Put, strike)
    return ql.BlackCalculator(payoff, future, iv * math.sqrt(years), math.exp(-rate * years))


def greeks(future, strike, years, rate, mid, right):
    iv = brentq(lambda vol: black(future, strike, years, rate, vol, right).value() - mid, .0001, 5.0)
    calc = black(future, strike, years, rate, iv, right)
    dt = min(1 / 365, years / 100)
    theta = (black(future, strike, years - dt, rate, iv, right).value() - calc.value()) / dt / 365
    return dict(iv=iv, delta=calc.deltaForward(), gamma=calc.gammaForward(), vega_1pct=calc.vega(years) / 100, theta_day=theta)


def snapshot(options: pd.DataFrame, cursor, max_age_s=900, oi_max_age_hours=96, require_oi=True):
    data = known_rows(options, cursor)
    if data.empty:
        return pd.DataFrame(), {"available": 0, "usable": 0, "excluded": {"no_available_snapshots": 1}}
    data = data.sort_values(["available_at", "ts", "sequence"]).drop_duplicates("option_id", keep="last")
    rows, excluded = [], {}
    for row in data.itertuples():
        reason = None
        years = (row.expiry - cursor).total_seconds() / YEAR_SECONDS
        age = (cursor - row.ts).total_seconds()
        oi_known = pd.notna(row.oi_available_at) and pd.notna(row.oi_asof) and row.oi_available_at <= cursor
        if row.style != "European":
            reason = "unsupported_style"
        elif years <= 60 / YEAR_SECONDS:
            reason = "expired_or_under_one_minute"
        elif age > max_age_s:
            reason = "stale_quote"
        elif row.bid < 0 or row.ask <= row.bid or not np.isfinite(row.ask):
            reason = "invalid_quote"
        elif (row.ask - row.bid) / max((row.ask + row.bid) / 2, .01) > .75:
            reason = "wide_quote"
        elif require_oi and not oi_known:
            reason = "unknown_or_unpublished_oi"
        elif require_oi and (cursor - row.oi_asof).total_seconds() > oi_max_age_hours * 3600:
            reason = "stale_oi"
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        try:
            result = greeks(row.future_price, row.strike, years, row.rate, (row.bid + row.ask) / 2, row.right)
        except (ValueError, RuntimeError, OverflowError):
            excluded["unsolved_iv"] = excluded.get("unsolved_iv", 0) + 1
            continue
        result.update(row._asdict())
        result.update(years=years, quote_age_s=age, oi_age_hours=(cursor - row.oi_asof).total_seconds() / 3600 if oi_known else np.nan, gamma_dollars_1pct=result["gamma"] * row.oi * row.multiplier * row.future_price ** 2 * .01)
        rows.append(result)
    return pd.DataFrame(rows), {"available": len(data), "usable": len(rows), "excluded": excluded}


def concentration(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    return frame.groupby(["strike", "right"], as_index=False).agg(oi=("oi", "sum"), gamma_dollars_1pct=("gamma_dollars_1pct", "sum"))


def scenario_surface(frame: pd.DataFrame, prices, scenario="All dealer long", iv_shift=0.0):
    rows = []
    for price in prices:
        exposure = 0.
        for row in frame.itertuples():
            sign = 1 if scenario == "All dealer long" else -1 if scenario == "All dealer short" else (1 if row.right == "C" else -1)
            gamma = black(price, row.strike, row.years, row.rate, max(.0001, row.iv + iv_shift), row.right).gammaForward()
            exposure += sign * gamma * row.oi * row.multiplier * price ** 2 * .01
        rows.append({"future_price": price, "assumed_gamma_dollars_1pct": exposure})
    return pd.DataFrame(rows)
