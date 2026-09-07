import numpy as np
import pandas as pd

from gamma_lab.models import RunConfig
from gamma_lab.options import snapshot

VARIANTS = ["Price baseline", "Gamma location", "Footprint", "Gamma + footprint"]


def add_locations(bars, options, max_age_s=900):
    result = bars.copy()
    result["gamma_zone"] = np.nan
    result["gamma_coverage"] = 0.
    for index, row in result.iterrows():
        # Freeze the zone at the start of the bar, before its auction is observed.
        chain, audit = snapshot(options, row.bar_start, max_age_s=max_age_s) if not options.empty else (pd.DataFrame(), {"available": 0, "usable": 0})
        if not chain.empty:
            weights = chain.groupby("strike").gamma_dollars_1pct.sum()
            result.loc[index, "gamma_zone"] = weights.idxmax()
            result.loc[index, "gamma_coverage"] = audit["usable"] / audit["available"]
    result["round_zone"] = np.floor(result.open / 25 + .5) * 25
    result["placebo_zone"] = result.round_zone + 12.5
    prior = result.groupby("session").close.last().shift(1)
    result["prior_close_zone"] = result.session.map(prior)
    return result


def signals(bars: pd.DataFrame, cfg: RunConfig, variant: str):
    cfg.validate()
    if variant not in VARIANTS:
        raise ValueError("Unknown hypothesis.")
    columns = ["ts", "direction", "setup", "zone", "variant", "session"]
    if len(bars) < 2:
        return pd.DataFrame(columns=columns)
    rows, last_entry = [], -100000
    history = {}
    for i in range(1, len(bars)):
        a, b = bars.iloc[i-1], bars.iloc[i]
        slot = (a.contract, a.ts.tz_convert("America/Chicago").strftime("%H:%M"))
        old_volumes = history.setdefault(slot, [])
        vol_floor = max(cfg.min_volume, float(np.median(old_volumes)) if old_volumes else cfg.min_volume)
        old_volumes.append(a.volume)
        if a.session != b.session or (b.ts - a.ts).total_seconds() != 60 or a.partial or b.partial or i - last_entry < cfg.cooldown_bars:
            continue
        use_gamma = variant in ["Gamma location", "Gamma + footprint"]
        use_flow = variant in ["Footprint", "Gamma + footprint"]
        zone = a.gamma_zone if use_gamma else a.round_zone
        if use_gamma and (not np.isfinite(zone) or a.gamma_coverage < .5):
            continue
        near = a.low <= zone + cfg.zone_ticks * .25 and a.high >= zone - cfg.zone_ticks * .25
        flow_good = a.classified_fraction >= cfg.min_classified and a.volume >= vol_floor
        bearish_pressure = flow_good and a.delta_ratio <= -cfg.delta_threshold
        bullish_pressure = flow_good and a.delta_ratio >= cfg.delta_threshold
        small_progress = abs(a.close - a.open) <= cfg.zone_ticks * .25
        direction, setup = 0, ""
        if variant == "Footprint":
            if bearish_pressure and small_progress and b.close > a.high:
                direction, setup = 1, "flow rejection"
            elif bullish_pressure and small_progress and b.close < a.low:
                direction, setup = -1, "flow rejection"
        elif near:
            if a.low < zone and b.close > zone and b.close > a.close and (not use_flow or (bearish_pressure and small_progress)):
                direction, setup = 1, "zone rejection"
            elif a.high > zone and b.close < zone and b.close < a.close and (not use_flow or (bullish_pressure and small_progress)):
                direction, setup = -1, "zone rejection"
            elif a.open <= zone < a.close and b.low > zone and (not use_flow or bullish_pressure):
                direction, setup = 1, "zone acceptance"
            elif a.open >= zone > a.close and b.high < zone and (not use_flow or bearish_pressure):
                direction, setup = -1, "zone acceptance"
        if direction:
            rows.append(dict(ts=b.ts, direction=direction, setup=setup, zone=zone, variant=variant, session=b.session))
            last_entry = i
    return pd.DataFrame(rows, columns=columns)


def encounters(bars: pd.DataFrame, zone_column: str, horizon=5, cooldown=5):
    rows, last = [], -100000
    bars = bars.reset_index(drop=True)
    for i, bar in bars.iterrows():
        if bar.partial or i - last < cooldown or pd.isna(bar[zone_column]) or not bar.low <= bar[zone_column] <= bar.high:
            continue
        future = bars.iloc[i+1:i+1+horizon]
        if len(future) != horizon or not future.session.eq(bar.session).all() or future.partial.any() or (future.ts.iloc[-1] - bar.ts).total_seconds() != horizon * 60:
            continue
        rows.append(dict(ts=bar.ts, session=bar.session, zone=bar[zone_column], reference=bar.close, forward_points=future.close.iloc[-1] - bar.close, upward_excursion=future.high.max() - bar.close, downward_excursion=bar.close - future.low.min(), horizon_bars=horizon))
        last = i
    return pd.DataFrame(rows)
