import numpy as np
import pandas as pd

from gamma_lab.models import session_id


def quote_book(market: pd.DataFrame) -> pd.DataFrame:
    if market.empty:
        return pd.DataFrame()
    full = market[market.kind.eq("quote")].copy()
    if not full.empty:
        full["bid_ts"] = full.ts
        full["ask_ts"] = full.ts
    sides = market[market.kind.isin(["bid", "ask"])].copy()
    books = [full] if not full.empty else []
    for symbol, group in sides.groupby("contract"):
        bids = group[group.kind.eq("bid")].sort_values("available_at")
        asks = group[group.kind.eq("ask")].sort_values("available_at")
        if bids.empty or asks.empty:
            continue
        for current, opposite, side in [(bids, asks, "bid"), (asks, bids, "ask")]:
            other = "ask" if side == "bid" else "bid"
            left = current[["ts", "available_at", "price"]].rename(columns={"price": side, "ts": f"{side}_ts"})
            right = opposite[["available_at", "price", "ts"]].rename(columns={"price": other, "ts": f"{other}_ts"})
            joined = pd.merge_asof(left, right, on="available_at", direction="backward", allow_exact_matches=False)
            joined["contract"] = symbol
            joined["ts"] = joined[["bid_ts", "ask_ts"]].max(axis=1)
            joined["bid_size"] = np.nan
            joined["ask_size"] = np.nan
            books.append(joined)
    if not books:
        return pd.DataFrame()
    book = pd.concat(books, ignore_index=True)
    book = book.sort_values(["available_at", "ts"], kind="stable")
    # Without a common cross-stream sequence, simultaneous differing quotes have no identifiable latest state.
    ambiguous = book.groupby(["contract", "available_at"])[["bid", "ask"]].transform("nunique").max(axis=1) > 1
    book.loc[ambiguous, ["bid", "ask"]] = np.nan
    return book.drop_duplicates(["contract", "available_at"], keep="last").reset_index(drop=True)


def classify(market: pd.DataFrame, max_age_ms=2000) -> pd.DataFrame:
    trades = market[market.kind.eq("trade")].copy().sort_values(["available_at", "sequence"], kind="stable")
    if trades.empty:
        return trades
    book = quote_book(market)
    outputs = []
    for symbol, group in trades.groupby("contract", sort=False):
        group = group.copy()
        quotes = book[book.contract.eq(symbol)] if not book.empty else book
        if not quotes.empty:
            right = quotes[["available_at", "bid", "ask", "bid_ts", "ask_ts"]].rename(columns={"available_at": "quote_available", "bid": "q_bid", "ask": "q_ask"})
            group = pd.merge_asof(group.sort_values("available_at"), right, left_on="available_at", right_on="quote_available", direction="backward", allow_exact_matches=False)
            valid_age = (group.ts - group.bid_ts).dt.total_seconds().between(0, max_age_ms / 1000) & (group.ts - group.ask_ts).dt.total_seconds().between(0, max_age_ms / 1000)
            group.loc[~valid_age, ["q_bid", "q_ask"]] = np.nan
        else:
            group["q_bid"] = np.nan
            group["q_ask"] = np.nan
        embedded = group.get("embedded", pd.Series(False, index=group.index)).fillna(False).astype(bool)
        group.loc[embedded, "q_bid"] = group.loc[embedded, "bid"]
        group.loc[embedded, "q_ask"] = group.loc[embedded, "ask"]
        valid = (group.q_ask > group.q_bid) & (group.q_bid > 0)
        unknown = group.side.eq("unknown")
        inferred_buy = unknown & valid & (group.price >= group.q_ask)
        inferred_sell = unknown & valid & (group.price <= group.q_bid)
        group.loc[inferred_buy, "side"] = "buy"
        group.loc[inferred_sell, "side"] = "sell"
        group.loc[inferred_buy | inferred_sell, "provenance"] = "causal quote inference"
        outputs.append(group)
    result = pd.concat(outputs, ignore_index=True).sort_values(["available_at", "sequence"], kind="stable")
    result["signed_size"] = result['size'] * result.side.map({"buy": 1, "sell": -1, "unknown": 0})
    result["session"] = session_id(result.available_at)
    result["cvd"] = result.groupby(["contract", "session"]).signed_size.cumsum()
    return result


def footprint(trades: pd.DataFrame):
    if trades.empty:
        return pd.DataFrame(columns=["price", "sell", "unknown", "buy", "delta", "total"])
    result = trades.pivot_table(index="price", columns="side", values="size", aggfunc="sum", fill_value=0).reindex(columns=["sell", "unknown", "buy"], fill_value=0)
    result["delta"] = result.buy - result.sell
    result["total"] = result.buy + result.sell + result.unknown
    return result.sort_index(ascending=False).reset_index()


def bars(trades: pd.DataFrame, cursor=None, seconds=60):
    if trades.empty:
        return pd.DataFrame()
    data = trades.copy()
    if cursor is not None:
        data = data[(data.ts <= cursor) & (data.available_at <= cursor)]
    if data.empty:
        return pd.DataFrame()
    data["bar_start"] = data.available_at.dt.floor(f"{seconds}s")
    data["known_size"] = np.where(data.side.ne("unknown"), data['size'], 0)
    result = data.groupby(["contract", "bar_start"], as_index=False).agg(open=("price", "first"), high=("price", "max"), low=("price", "min"), close=("price", "last"), volume=("size", "sum"), delta=("signed_size", "sum"), known_volume=("known_size", "sum"))
    result["ts"] = result.bar_start + pd.Timedelta(seconds=seconds)
    result["session"] = session_id(result.ts - pd.Timedelta(nanoseconds=1))
    result["delta_ratio"] = result.delta / result.volume.replace(0, np.nan)
    result["classified_fraction"] = result.known_volume / result.volume.replace(0, np.nan)
    watermark = pd.Timestamp(cursor) if cursor is not None else data.available_at.max()
    result["partial"] = result.ts > watermark
    return result


def ofi(book: pd.DataFrame, complete_updates=False):
    if not complete_updates or book.empty or book[["bid_size", "ask_size"]].isna().any().any():
        raise ValueError("OFI requires attested complete quote updates with displayed bid/ask sizes. Trade-associated snapshots are insufficient.")
    b = book.copy().sort_values(["contract", "available_at"])
    b["session"] = session_id(b.available_at)
    p = b.groupby(["contract", "session"])[["bid", "ask", "bid_size", "ask_size"]].shift(1)
    valid = (b.ask > b.bid) & (p.ask > p.bid) & (b.bid_size >= 0) & (b.ask_size >= 0)
    b["ofi"] = np.where(valid, (b.bid >= p.bid) * b.bid_size - (b.bid <= p.bid) * p.bid_size - (b.ask <= p.ask) * b.ask_size + (b.ask >= p.ask) * p.ask_size, np.nan)
    return b
