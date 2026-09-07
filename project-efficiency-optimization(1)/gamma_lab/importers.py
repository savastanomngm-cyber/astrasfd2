from io import BytesIO, StringIO
import re

import numpy as np
import pandas as pd

from gamma_lab.models import contract

TIME_FIELDS = ["ts", "available_at", "expiry", "oi_available_at", "oi_asof"]
MARKET_FIELDS = ["ts", "available_at", "contract", "kind", "price", "size", "side", "bid", "ask", "bid_size", "ask_size"]
OPTION_FIELDS = ["ts", "available_at", "option_id", "contract", "expiry", "strike", "right", "style", "bid", "ask", "future_price", "rate", "multiplier", "oi", "oi_asof", "oi_available_at"]


def utc(values, timezone="UTC"):
    def parse(value):
        if pd.isna(value) or value == "":
            return pd.NaT
        t = pd.Timestamp(value)
        return t.tz_localize(timezone, ambiguous="raise", nonexistent="raise").tz_convert("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return pd.to_datetime(values.map(parse), utc=True)


def _nt_time(value):
    match = re.fullmatch(r"(\d{8}) (\d{6})(?: (\d{1,7}))?", value.strip())
    if not match:
        raise ValueError(f"Not a NinjaTrader tick timestamp: {value}")
    t = pd.to_datetime(match[1] + match[2], format="%Y%m%d%H%M%S", utc=True)
    return t + pd.Timedelta(int((match[3] or "0").ljust(7, "0")) * 100, unit="ns")


def ninjatrader(raw: bytes, symbol: str, kind="Last") -> pd.DataFrame:
    contract(symbol)
    rows = []
    for seq, line in enumerate(raw.decode("utf-8-sig").splitlines()):
        if not line.strip():
            continue
        parts = [x.strip() for x in line.split(";")]
        if len(parts) not in (3, 5) or kind not in ("Last", "Bid", "Ask") or (kind != "Last" and len(parts) != 3):
            raise ValueError(f"Line {seq + 1}: only 3-field tick or 5-field Last tick-replay text is supported; bars/Market Replay are not.")
        ts = _nt_time(parts[0])
        row = dict(ts=ts, available_at=ts, contract=symbol, kind="trade" if kind == "Last" else kind.lower(), price=float(parts[1]), size=float(parts[-1]), side="unknown", provenance="unclassified", sequence=seq, clock="event-time replay; receipt unavailable")
        if len(parts) == 5:
            row.update(bid=float(parts[2]), ask=float(parts[3]), embedded=True)
        rows.append(row)
    return validate(pd.DataFrame(rows), "market")


def canonical(raw: bytes, filename: str, kind: str, timezone: str, convention: str) -> pd.DataFrame:
    if convention != "event":
        raise ValueError("This importer accepts tick/snapshot event timestamps, not OHLC bars.")
    frame = pd.read_parquet(BytesIO(raw)) if filename.lower().endswith(".parquet") else pd.read_csv(BytesIO(raw))
    if len(frame) > 2_000_000:
        raise ValueError("Limit each import to 2 million records; split larger files by session.")
    for col in TIME_FIELDS:
        if col in frame:
            frame[col] = utc(frame[col], timezone)
    if "available_at" not in frame:
        frame["available_at"] = frame["ts"]
        frame["clock"] = "event-time replay; receipt unavailable"
    else:
        frame["clock"] = "provided availability"
    if kind == "market":
        if "side" not in frame:
            frame["side"] = "unknown"
        frame["provenance"] = "user-supplied aggressor"
    frame["sequence"] = np.arange(len(frame))
    return validate(frame, kind)


def databento_trades(raw: bytes, symbol: str) -> pd.DataFrame:
    """Scoped adapter: pretty-price, pretty-timestamp trades CSV, one resolved contract."""
    frame = pd.read_csv(BytesIO(raw))
    required = {"ts_event", "ts_recv", "price", "size", "side", "action", "instrument_id"}
    if not required <= set(frame):
        raise ValueError("Only Databento trades CSV with pretty timestamps/prices is supported. DBN and mbp/mbo schemas require conversion.")
    if frame.instrument_id.nunique() != 1 or not frame.action.eq("T").all():
        raise ValueError("Select exactly one resolved instrument and the trades schema.")
    if not frame.ts_event.astype(str).str.contains("T|:", regex=True).all() or pd.to_numeric(frame.price).max() > 1_000_000:
        raise ValueError("Export human-readable timestamps and decimal prices, not fixed-point integers.")
    frame["ts"] = utc(frame.ts_event)
    frame["available_at"] = utc(frame.ts_recv)
    frame["contract"] = symbol
    frame["kind"] = "trade"
    frame["side"] = frame.side.map({"B": "buy", "A": "sell", "N": "unknown"}).fillna("unknown")
    frame["provenance"] = "exchange aggressor"
    frame["clock"] = "provided availability"
    if "sequence" not in frame:
        frame["sequence"] = np.arange(len(frame))
    return validate(frame, "market")


def validate(frame: pd.DataFrame, kind: str) -> pd.DataFrame:
    if kind not in ("market", "options"):
        raise ValueError("Choose market or options records.")
    if frame.empty:
        raise ValueError("File has no records.")
    required = {"ts", "available_at", "contract", "kind", "price", "size"} if kind == "market" else set(OPTION_FIELDS) - {"oi_asof", "oi_available_at"}
    missing = required - set(frame)
    if missing:
        raise ValueError("Missing columns: " + ", ".join(sorted(missing)))
    frame = frame.copy()
    if frame[["ts", "available_at"]].isna().any().any() or (frame.available_at < frame.ts).any():
        raise ValueError("Event/availability timestamps must exist and availability cannot precede event time.")
    for symbol in frame.contract.unique():
        contract(symbol)
    numeric = ["price", "size"] if kind == "market" else ["strike", "bid", "ask", "future_price", "rate", "multiplier", "oi"]
    for col in numeric:
        frame[col] = pd.to_numeric(frame[col], errors="raise")
        if not np.isfinite(frame[col]).all():
            raise ValueError(f"Nonfinite {col}.")
    if kind == "market":
        if not frame.kind.isin(["trade", "quote", "bid", "ask"]).all():
            raise ValueError("kind must be trade, quote, bid, or ask.")
        if (frame.price <= 0).any() or (frame['size'] < 0).any() or ((frame['size'] % 1) != 0).any():
            raise ValueError("Positive prices and nonnegative integer sizes required.")
        executable_prices = frame.loc[frame.kind.ne("quote"), "price"]
        if not np.isclose(executable_prices / .25, np.round(executable_prices / .25), rtol=0, atol=1e-7).all():
            raise ValueError("Off-tick futures prices detected; no silent rounding.")
        frame["side"] = frame.get("side", pd.Series("unknown", index=frame.index)).fillna("unknown")
        if not frame.side.isin(["buy", "sell", "unknown"]).all():
            raise ValueError("side must be buy, sell, or unknown.")
        for col in ["bid", "ask", "bid_size", "ask_size"]:
            frame[col] = pd.to_numeric(frame.get(col, np.nan), errors="raise")
        quoted = frame.kind.eq("quote")
        if frame.loc[quoted, ["bid", "ask"]].isna().any().any():
            raise ValueError("Quote records require bid and ask.")
        for col in ["bid", "ask"]:
            v = frame[col].dropna()
            if not np.isfinite(v).all() or not np.isclose(v / .25, np.round(v / .25), rtol=0, atol=1e-7).all():
                raise ValueError(f"Invalid/off-tick {col}.")
        for col in ["bid_size", "ask_size"]:
            v = frame[col].dropna()
            if not np.isfinite(v).all() or (v < 0).any() or (v % 1 != 0).any():
                raise ValueError(f"Invalid {col}; require nonnegative integers or missing values.")
        if (frame.loc[frame.kind.eq("trade"), "size"] <= 0).any():
            raise ValueError("Trade sizes must be positive.")
    else:
        if frame.expiry.isna().any() or frame.option_id.isna().any():
            raise ValueError("Options require an expiration timestamp and an option ID.")
        if not frame.right.isin(["C", "P"]).all() or not frame['style'].isin(["European", "American"]).all():
            raise ValueError("right must be C/P; style must explicitly be European/American.")
        for col in ["oi_asof", "oi_available_at"]:
            if col not in frame:
                frame[col] = pd.NaT
            frame[col] = pd.to_datetime(frame[col], utc=True)
        if (frame.strike <= 0).any() or (frame.future_price <= 0).any() or (frame.oi < 0).any() or ((frame.oi % 1) != 0).any():
            raise ValueError("Invalid strike, futures price, or open interest.")
        expected = frame.contract.map(lambda s: contract(s).multiplier)
        if not np.isclose(frame.multiplier, expected).all():
            raise ValueError("Multiplier must match the ES/NQ futures underlying.")
        if (frame.oi_available_at < frame.oi_asof).any():
            raise ValueError("OI publication precedes its observation.")
    if "sequence" not in frame:
        frame["sequence"] = np.arange(len(frame))
    return frame


def audit(frame: pd.DataFrame, kind: str) -> dict:
    gaps = frame.sort_values("ts").groupby("contract").ts.diff().dt.total_seconds()
    result = {"records": len(frame), "contracts": ", ".join(frame.contract.unique()), "start": str(frame.ts.min()), "end": str(frame.ts.max()), "out_of_order_input": not frame.ts.is_monotonic_increasing, "identical_records_retained": int(frame.drop(columns=["sequence"], errors="ignore").duplicated().sum()), "gaps_over_60s_review_required": int((gaps > 60).sum()), "availability": ", ".join(frame.get("clock", pd.Series(["provided"])).unique())}
    if kind == "market":
        result.update(trades=int(frame.kind.eq("trade").sum()), quote_records=int(frame.kind.ne("trade").sum()), invalid_embedded_or_full_quotes=int(((frame.bid >= frame.ask) | (frame.bid <= 0)).sum()))
    else:
        result.update(unknown_oi_availability=int(frame.oi_available_at.isna().sum()), unsupported_american=int(frame['style'].eq("American").sum()))
    return result


def template(kind: str) -> bytes:
    return (",".join(MARKET_FIELDS if kind == "market" else OPTION_FIELDS) + "\n").encode()
