from dataclasses import dataclass, asdict
import hashlib
import json
import re

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Contract:
    symbol: str
    root: str
    tick: float
    multiplier: float


def contract(symbol: str) -> Contract:
    if not isinstance(symbol, str) or not re.fullmatch(
        r"(?:ES|NQ)(?:[FGHJKMNQUVXZ]\d{1,4}| \d{2}-\d{2})", symbol
    ):
        raise ValueError("Use an individual ES/NQ contract, e.g. ESU6 or ES 09-26; continuous symbols are unsupported.")
    root = symbol[:2]
    return Contract(symbol, root, .25, 50.0 if root == "ES" else 20.0)


def session_id(times: pd.Series) -> pd.Series:
    local = pd.to_datetime(times, utc=True).dt.tz_convert("America/Chicago")
    # Remove the timezone before adding calendar hours: elapsed-hour arithmetic breaks DST sessions.
    return (local.dt.tz_localize(None) + pd.Timedelta(hours=7)).dt.strftime("%Y-%m-%d")


def known_rows(frame: pd.DataFrame, cursor) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    cursor = pd.Timestamp(cursor)
    return frame.loc[(frame.ts <= cursor) & (frame.available_at <= cursor)].copy()


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class RunConfig:
    capital: float = 25_000.0
    fee_per_side: float = 2.50
    slippage_ticks: int = 1
    latency_ms: int = 250
    quote_age_ms: int = 2000
    risk_fraction: float = .005
    max_contracts: int = 1
    session_loss: float = 500.0
    stop_ticks: int = 12
    target_ticks: int = 20
    hold_bars: int = 5
    delta_threshold: float = .25
    zone_ticks: int = 8
    min_volume: int = 20
    min_classified: float = .8
    cooldown_bars: int = 5

    def validate(self):
        for value in asdict(self).values():
            if not np.isfinite(value):
                raise ValueError("Configuration must be finite.")
        if self.capital <= 0 or not 0 < self.risk_fraction <= .05:
            raise ValueError("Positive capital and risk fraction in (0, 5%] required.")
        for name in ["slippage_ticks", "latency_ms", "quote_age_ms", "max_contracts", "stop_ticks", "target_ticks", "hold_bars", "zone_ticks", "min_volume", "cooldown_bars"]:
            value = getattr(self, name)
            if int(value) != value or value < (0 if name in ["slippage_ticks", "latency_ms"] else 1):
                raise ValueError(f"Invalid {name}.")
        if self.fee_per_side < 0 or self.session_loss <= 0 or not 0 <= self.delta_threshold <= 1 or not 0 <= self.min_classified <= 1:
            raise ValueError("Invalid fees, loss limit or feature thresholds.")
        return self
