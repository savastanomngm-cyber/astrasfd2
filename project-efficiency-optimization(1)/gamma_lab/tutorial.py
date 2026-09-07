import numpy as np
import pandas as pd

from gamma_lab.importers import validate
from gamma_lab.models import contract
from gamma_lab.options import black, YEAR_SECONDS


def tutorial(symbol="ESU6", sessions=6):
    spec = contract(symbol)
    rng = np.random.default_rng(42 if spec.root == "ES" else 43)
    base = 5600. if spec.root == "ES" else 20000.
    market, options = [], []
    seq = 0
    for day in range(sessions):
        start = pd.Timestamp("2026-08-03T13:30:00Z") + pd.offsets.BDay(day)
        price = base
        for i in range(60 * 60):
            ts = start + pd.Timedelta(seconds=i)
            price = round((price + rng.choice([-.5, -.25, 0, .25, .5]) + (base - price) * .002) * 4) / 4
            bid, ask = price - .25, price + .25
            market.append(dict(ts=ts, available_at=ts, contract=symbol, kind="quote", price=price, size=0, bid=bid, ask=ask, bid_size=int(rng.integers(5, 40)), ask_size=int(rng.integers(5, 40)), side="unknown", sequence=seq, provenance="synthetic", clock="synthetic"))
            seq += 1
            buy = bool(rng.integers(0, 2))
            t = ts + pd.Timedelta(milliseconds=100)
            market.append(dict(ts=t, available_at=t, contract=symbol, kind="trade", price=ask if buy else bid, size=int(rng.integers(1, 12)), side="buy" if buy else "sell", provenance="synthetic aggressor", sequence=seq, clock="synthetic"))
            seq += 1
            if i % 300 == 0:
                expiry = start.normalize() + pd.Timedelta(days=4, hours=20)
                years = (expiry - ts).total_seconds() / YEAR_SECONDS
                for strike in np.arange(base - 40, base + 41, 10):
                    for right in ["C", "P"]:
                        value = black(price, strike, years, .04, .18 if spec.root == "ES" else .24, right).value()
                        options.append(dict(ts=ts, available_at=ts, option_id=f"{symbol}-{expiry.isoformat()}-{strike}-{right}", contract=symbol, expiry=expiry, strike=strike, right=right, style="European", bid=max(.01, value - .125), ask=value + .125, future_price=price, rate=.04, multiplier=spec.multiplier, oi=int(100 + 2500 * np.exp(-((strike - base) / 14) ** 2)), oi_asof=start.normalize() - pd.Timedelta(hours=4), oi_available_at=start.normalize() + pd.Timedelta(hours=10), sequence=seq, clock="synthetic"))
    return validate(pd.DataFrame(market), "market"), validate(pd.DataFrame(options), "options")
