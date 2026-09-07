from dataclasses import asdict
import math

import numpy as np
import pandas as pd

from gamma_lab.models import RunConfig, contract, session_id


def size_contracts(equity, cfg, spec):
    risk = cfg.stop_ticks * spec.tick * spec.multiplier + 2 * cfg.fee_per_side + 2 * cfg.slippage_ticks * spec.tick * spec.multiplier
    return max(0, min(cfg.max_contracts, math.floor(max(0, equity) * cfg.risk_fraction / risk)))


def simulate(book: pd.DataFrame, signals: pd.DataFrame, cfg: RunConfig, symbol: str):
    cfg.validate()
    spec = contract(symbol)
    quotes = book[book.contract.eq(symbol)].copy() if not book.empty else book
    if quotes.empty:
        return {"trades": pd.DataFrame(), "equity": pd.DataFrame(), "orders": pd.DataFrame(), "open_position": None, "status": "No execution quotes; no fills", "config": asdict(cfg)}
    quotes = quotes.sort_values("available_at", kind="stable")
    quotes["session"] = session_id(quotes.available_at)
    if not signals.empty and not signals.direction.isin([-1, 1]).all():
        raise ValueError("Signal direction must be -1 or 1.")
    candidates = signals.sort_values("ts").to_dict("records")
    signal_index, cash, position, pending = 0, cfg.capital, None, None
    trades, orders, path = [], [], []
    current_session, session_start, halted = None, cfg.capital, False
    last_time = None
    latency = pd.Timedelta(milliseconds=cfg.latency_ms)
    for q in quotes.itertuples():
        t = q.available_at
        session = q.session
        if session != current_session:
            if pending and pending["type"] == "entry":
                orders.append(dict(ts=t, status="entry cancelled at session boundary", reason=pending["signal"]["setup"]))
                pending = None
            current_session, session_start, halted = session, cash, False
            if position:
                pending = dict(type="exit", eligible=t + latency, trigger=t, reason="session boundary / data gap")
        if position and last_time is not None and (t - last_time).total_seconds() * 1000 > cfg.quote_age_ms:
            pending = pending or dict(type="exit", eligible=last_time + pd.Timedelta(milliseconds=cfg.quote_age_ms) + latency, trigger=last_time + pd.Timedelta(milliseconds=cfg.quote_age_ms), reason="quote gap / stale-data halt")
        if position and pending is None and t >= position["deadline"]:
            pending = dict(type="exit", eligible=position["deadline"] + latency, trigger=position["deadline"], reason="time exit")
        while signal_index < len(candidates) and candidates[signal_index]["ts"] <= t:
            signal = candidates[signal_index]
            signal_index += 1
            if signal["session"] != session:
                orders.append(dict(ts=signal["ts"], status="expired: prior-session signal", reason=signal["setup"]))
                continue
            if position is None and pending is None and not halted:
                pending = dict(type="entry", eligible=signal["ts"] + latency, trigger=signal["ts"], signal=signal)
            else:
                orders.append(dict(ts=signal["ts"], status="skipped: position, pending order or session halt", reason=signal["setup"]))
        valid = np.isfinite(q.bid) and np.isfinite(q.ask) and 0 < q.bid < q.ask and 0 <= (t - q.bid_ts).total_seconds() <= cfg.quote_age_ms / 1000 and 0 <= (t - q.ask_ts).total_seconds() <= cfg.quote_age_ms / 1000
        if pending and pending["type"] == "entry" and (t - pending["trigger"]).total_seconds() > cfg.quote_age_ms / 1000:
            orders.append(dict(ts=t, status="entry expired: missing timely quote", reason=pending["signal"]["setup"]))
            pending = None
        if not valid:
            if position and pending is None:
                pending = dict(type="exit", eligible=t + latency, trigger=t, reason="invalid quote / stale-data halt")
            continue
        mark = cash + ((q.bid if position["direction"] > 0 else q.ask) - position["entry"]) * position["direction"] * position["qty"] * spec.multiplier if position else cash
        if mark - session_start <= -cfg.session_loss:
            halted = True
            if pending and pending["type"] == "entry":
                pending = None
            if position and pending is None:
                pending = dict(type="exit", eligible=t + latency, trigger=t, reason="session loss halt")
        if pending and t >= pending["eligible"] and t > pending["trigger"]:
            order = pending
            if order["type"] == "entry" and position is None and not halted:
                signal = order["signal"]
                direction = int(signal["direction"])
                qty = size_contracts(cash, cfg, spec)
                displayed = getattr(q, "ask_size" if direction > 0 else "bid_size", np.nan)
                if np.isfinite(displayed):
                    qty = min(qty, max(0, int(displayed)))
                if qty > 0:
                    price = (q.ask if direction > 0 else q.bid) + direction * cfg.slippage_ticks * spec.tick
                    fee = qty * cfg.fee_per_side
                    cash -= fee
                    position = dict(entry_time=t, entry=price, direction=direction, qty=qty, entry_fee=fee, deadline=t + pd.Timedelta(minutes=cfg.hold_bars), stop=price - direction * cfg.stop_ticks * spec.tick, target=price + direction * cfg.target_ticks * spec.tick, setup=signal["setup"], variant=signal["variant"], signal_time=signal["ts"], zone=signal.get("zone"), contract=symbol)
                    orders.append(dict(ts=t, status="paper entry filled", reason=signal["setup"]))
                else:
                    orders.append(dict(ts=t, status="no fill: integer risk/size cap", reason=signal["setup"]))
                pending = None
            elif order["type"] == "exit" and position:
                direction = position["direction"]
                price = (q.bid if direction > 0 else q.ask) - direction * cfg.slippage_ticks * spec.tick
                fee = position["qty"] * cfg.fee_per_side
                pnl = (price - position["entry"]) * direction * position["qty"] * spec.multiplier
                cash += pnl - fee
                trades.append({**position, "exit_time": t, "exit": price, "exit_fee": fee, "net_pnl": pnl - fee - position["entry_fee"], "reason": order["reason"], "session": session})
                orders.append(dict(ts=t, status="paper exit filled", reason=order["reason"]))
                position, pending = None, None
        if position:
            executable = q.bid if position["direction"] > 0 else q.ask
            move = (executable - position["entry"]) * position["direction"]
            if pending is None and (move <= -cfg.stop_ticks * spec.tick or move >= cfg.target_ticks * spec.tick):
                pending = dict(type="exit", eligible=t + latency, trigger=t, reason="stop" if move < 0 else "target")
            mark = cash + move * position["qty"] * spec.multiplier
        else:
            mark = cash
        path.append(dict(ts=t, session=session, equity=mark, cash=cash, position=position["direction"] * position["qty"] if position else 0))
        last_time = t
    if pending:
        orders.append(dict(ts=pending["trigger"], status="unfilled at data end", reason=pending.get("reason", "entry")))
    for signal in candidates[signal_index:]:
        orders.append(dict(ts=signal["ts"], status="unfilled: no later quote", reason=signal["setup"]))
    return {"trades": pd.DataFrame(trades), "equity": pd.DataFrame(path), "orders": pd.DataFrame(orders), "open_position": position, "status": "Open position remains marked; no fabricated terminal liquidation" if position else "Completed replay", "config": asdict(cfg)}
