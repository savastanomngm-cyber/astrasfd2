from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, strategies as strategies

from gamma_lab.execution import simulate, size_contracts
from gamma_lab.importers import validate, canonical, utc, ninjatrader
from gamma_lab.models import RunConfig, contract, session_id, known_rows
from gamma_lab.options import black, greeks, snapshot
from gamma_lab.orderflow import classify, quote_book, footprint, bars, ofi
from gamma_lab.setups import signals, add_locations, VARIANTS
from gamma_lab.statistics import block_interval, deflated_sharpe
from gamma_lab.storage import Store, reject_overlapping_sources
from gamma_lab.tutorial import tutorial
from gamma_lab.evaluation import prepare, run_experiment

T = pd.Timestamp("2026-08-03T13:30:00Z")


def quote(seconds=0, bid=5600., ask=5600.25, symbol="ESU6"):
    t = T + pd.Timedelta(seconds=seconds)
    return dict(ts=t, available_at=t, contract=symbol, kind="quote", price=bid, size=0, bid=bid, ask=ask, bid_size=10, ask_size=10, side="unknown")


def trade(seconds=.1, price=5600.25, side="unknown", size=3):
    t = T + pd.Timedelta(seconds=seconds)
    return dict(ts=t, available_at=t, contract="ESU6", kind="trade", price=price, size=size, side=side)


def market(rows):
    return validate(pd.DataFrame(rows), "market")


def candidate(t=T, direction=1):
    return pd.DataFrame([dict(ts=t, direction=direction, setup="test", zone=5600., variant="Price baseline", session=session_id(pd.Series([t])).iloc[0])])


@pytest.fixture(scope="module")
def sample():
    return tutorial(sessions=6)


@pytest.fixture(scope="module")
def prepared(sample):
    return prepare(*sample)


@given(strategies.lists(strategies.tuples(strategies.integers(1, 100), strategies.sampled_from(["buy", "sell", "unknown"])), min_size=1, max_size=40))
def test_footprint_volume_reconciles(values):
    records = [trade(i, side=side, size=size) for i, (size, side) in enumerate(values)]
    ticks = classify(market(records))
    fp = footprint(ticks)
    assert fp.total.sum() == sum(size for size, _ in values)
    assert fp.delta.sum() == sum(size * {"buy": 1, "sell": -1, "unknown": 0}[side] for size, side in values)


def test_unknown_not_forced_and_future_quotes_not_joined():
    m = market([trade(0), quote(1)])
    result = classify(m)
    assert result.side.iloc[0] == "unknown"
    assert footprint(result).unknown.sum() == 3


def test_stale_quotes_not_used_for_inference():
    assert classify(market([quote(0), trade(3)]), max_age_ms=2000).side.iloc[0] == "unknown"


def test_no_same_timestamp_quote_inference():
    assert classify(market([quote(0), trade(0)])).side.iloc[0] == "unknown"


def test_available_at_not_only_event_time():
    late = trade(0)
    late["available_at"] = T + pd.Timedelta(seconds=2)
    assert known_rows(market([late]), T + pd.Timedelta(seconds=1)).empty


def test_oi_not_used_before_publication(sample):
    _, options = sample
    cursor = options.ts.min()
    future_oi = options.copy()
    future_oi["oi_available_at"] = cursor + pd.Timedelta(hours=1)
    chain, quality = snapshot(future_oi, cursor)
    assert chain.empty
    assert quality["excluded"]["unknown_or_unpublished_oi"] > 0


def test_american_options_are_excluded(sample):
    _, options = sample
    altered = options.copy()
    altered["style"] = "American"
    chain, quality = snapshot(altered, options.ts.min())
    assert chain.empty
    assert quality["excluded"]["unsupported_style"] > 0


@pytest.mark.parametrize("right", ["C", "P"])
def test_black_gamma_matches_numerical_derivative(right):
    f, k, years, r, iv, h = 5600., 5600., .1, .04, .2, .1
    calc = black(f, k, years, r, iv, right)
    numerical = (black(f+h, k, years, r, iv, right).value() - 2*calc.value() + black(f-h, k, years, r, iv, right).value()) / h**2
    assert calc.gammaForward() > 0
    assert numerical == pytest.approx(calc.gammaForward(), rel=1e-5)
    assert greeks(f, k, years, r, calc.value(), right)["iv"] == pytest.approx(iv)


def test_replay_determinism_and_no_same_event_fill():
    book = quote_book(market([quote(0), quote(1), quote(2)]))
    cfg = RunConfig(risk_fraction=.01, latency_ms=0)
    first = simulate(book, candidate(), cfg, "ESU6")
    second = simulate(book, candidate(), cfg, "ESU6")
    pd.testing.assert_frame_equal(first["equity"], second["equity"])
    assert first["open_position"]["entry_time"] == T + pd.Timedelta(seconds=1)
    assert first["open_position"]["entry"] == 5600.5
    assert first["trades"].empty


def test_fill_not_before_latency():
    book = quote_book(market([quote(0), quote(.2), quote(.4), quote(.6)]))
    result = simulate(book, candidate(), RunConfig(risk_fraction=.01, latency_ms=500), "ESU6")
    assert result["open_position"]["entry_time"] == T + pd.Timedelta(seconds=.6)


def test_missing_quotes_block_fills():
    result = simulate(pd.DataFrame(), candidate(), RunConfig(), "ESU6")
    assert result["trades"].empty and result["open_position"] is None


def test_late_entry_expires():
    book = quote_book(market([quote(0), quote(5)]))
    result = simulate(book, candidate(), RunConfig(risk_fraction=.01), "ESU6")
    assert result["open_position"] is None
    assert result["orders"].status.str.contains("expired").any()


def test_stop_can_slip_and_fees_are_per_side():
    book = quote_book(market([quote(0), quote(1), quote(2, 5595., 5595.25), quote(3, 5590., 5590.25)]))
    cfg = RunConfig(risk_fraction=.01)
    result = simulate(book, candidate(), cfg, "ESU6")
    closed = result["trades"].iloc[0]
    assert closed.exit == 5589.75
    assert closed.net_pnl == pytest.approx((closed.exit - closed.entry) * 50 - 5)
    assert closed.net_pnl < -cfg.stop_ticks * .25 * 50
    assert closed.exit_time > T + pd.Timedelta(seconds=2)


def test_quantity_integer_and_instrument_multiplier():
    cfg = RunConfig(risk_fraction=.005)
    assert size_contracts(25000, cfg, contract("ESU6")) == 0
    assert size_contracts(25000, cfg, contract("NQU6")) == 1
    assert contract("ESU6").multiplier == 50
    assert contract("NQU6").multiplier == 20
    with pytest.raises(ValueError):
        replace(cfg, max_contracts=1.5).validate()
    with pytest.raises(ValueError):
        contract("ES.c.0")


def test_displayed_entry_size_caps_fill():
    records = [quote(0), quote(1)]
    records[-1]["ask_size"] = 0
    result = simulate(quote_book(market(records)), candidate(), RunConfig(risk_fraction=.01), "ESU6")
    assert result["open_position"] is None


def test_stale_quote_event_does_not_fill():
    record = quote(0)
    record["available_at"] = T + pd.Timedelta(seconds=5)
    result = simulate(quote_book(market([record])), candidate(T + pd.Timedelta(seconds=4)), RunConfig(risk_fraction=.01), "ESU6")
    assert result["open_position"] is None


def test_partial_final_bar_is_not_closed():
    result = bars(classify(market([trade(0, side="buy"), trade(61, side="buy")])) )
    assert result.partial.tolist() == [False, True]


def test_appending_future_changes_no_earlier_signals(sample, prepared):
    m, o = sample
    cut = T + pd.Timedelta(minutes=40)
    past_m, past_o = known_rows(m, cut), known_rows(o, cut)
    prefix, _ = prepare(past_m, past_o)
    all_bars, _ = prepared
    for variant in VARIANTS:
        prior = signals(prefix, RunConfig(), variant)
        full = signals(all_bars, RunConfig(), variant)
        pd.testing.assert_frame_equal(prior.reset_index(drop=True), full[full.ts <= cut].reset_index(drop=True))


@pytest.mark.parametrize("times,expected", [
    (["2026-03-08T21:59:59Z", "2026-03-08T22:00:00Z"], ["2026-03-08", "2026-03-09"]),
    (["2026-11-01T22:59:59Z", "2026-11-01T23:00:00Z"], ["2026-11-01", "2026-11-02"]),
])
def test_dst_session_boundary(times, expected):
    assert session_id(pd.Series(times)).tolist() == expected


def test_ambiguous_local_time_rejected():
    with pytest.raises(Exception):
        utc(pd.Series(["2026-11-01 01:30:00"]), "America/Chicago")


def test_off_tick_large_nq_prices_rejected():
    with pytest.raises(ValueError, match="Off-tick"):
        market([dict(trade(), contract="NQU6", price=20000.1)])


def test_half_tick_quote_midpoint_is_not_an_execution_price():
    record = dict(quote(), price=5600.125)
    validated = market([record])
    assert validated.price.iloc[0] == 5600.125
    assert quote_book(validated).bid.iloc[0] == 5600.
    with pytest.raises(ValueError, match="off-tick ask"):
        market([dict(record, ask=5600.3)])


def test_holdout_gamma_cannot_enable_development_variant(tmp_path, prepared):
    store = Store(tmp_path)
    candles, book = prepared
    candles = candles.copy()
    days = sorted(candles.session.unique())
    study = store.study(["gamma-isolation"], "ESU6", days)
    candles.loc[~candles.session.isin(study["holdout"]), "gamma_zone"] = np.nan
    cfg = RunConfig(risk_fraction=.01)
    first = run_experiment(store, study, candles, book, cfg)
    candles["gamma_zone"] = np.nan
    second = run_experiment(store, study, candles, book, cfg)
    pd.testing.assert_frame_equal(first["summary"], second["summary"])
    pd.testing.assert_frame_equal(first["folds"], second["folds"])
    assert "Gamma location" not in first["results"]


def test_invalid_sizes_rejected():
    with pytest.raises(ValueError):
        market([dict(quote(), bid_size=-1)])
    with pytest.raises(ValueError):
        market([trade(size=0)])


def test_ofi_requires_complete_updates():
    book = quote_book(market([quote(0), quote(1)]))
    with pytest.raises(ValueError, match="complete"):
        ofi(book)
    assert len(ofi(book, complete_updates=True)) == 2


def test_conflicting_same_time_quotes_are_invalid():
    book = quote_book(market([quote(0), quote(0, 5601., 5601.25)]))
    assert book.bid.isna().all()


def test_store_roundtrip_immutable_and_overlap_guard(tmp_path):
    store = Store(tmp_path)
    frame = market([quote(0), trade(.1)])
    raw = frame.to_csv(index=False).encode()
    ident = store.add(raw, frame, "market", {"synthetic": True})
    assert store.add(raw, frame, "market", {"synthetic": True}) == ident
    assert len(store.sources()) == 1
    loaded = store.load([ident])
    assert len(loaded) == 2
    assert loaded.source_id.eq(ident).all()
    duplicate = loaded.copy()
    duplicate["source_id"] = "second"
    with pytest.raises(ValueError, match="Overlapping"):
        reject_overlapping_sources(pd.concat([loaded, duplicate]))
    with pytest.raises(ValueError, match="Unknown"):
        store.load(["../../etc"])


def test_holdout_access_persists_and_prevents_fresh_claim(tmp_path):
    store = Store(tmp_path)
    study = store.study(["one"], "ESU6", ["2026-08-03", "2026-08-04"])
    assert not study["opened_at"]
    store.open_holdout(study["id"])
    reopened = Store(tmp_path).study(["one"], "ESU6", study["sessions"])
    assert reopened["opened_at"]
    changed_sources = store.study(["two"], "ESU6", study["sessions"])
    assert changed_sources["previously_exposed"] == ["2026-08-04"]


def test_walk_forward_registry_and_holdout_isolation(tmp_path, sample, prepared):
    store = Store(tmp_path)
    b, q = prepared
    days = sorted(b.session.unique())
    study = store.study(["test-source"], "ESU6", days)
    result = run_experiment(store, study, b, q, RunConfig(risk_fraction=.01))
    assert not result["folds"].session.isin(study["holdout"]).any()
    assert len(store.runs()) > 1
    assert store.artifacts(result["run_id"])
    future = b.copy()
    mask = future.session.isin(study["holdout"])
    future.loc[mask, ["open", "high", "low", "close"]] += 1000
    other = run_experiment(store, study, future, q, RunConfig(risk_fraction=.01))
    pd.testing.assert_frame_equal(result["summary"], other["summary"])
    assert not store.study(["test-source"], "ESU6", days)["opened_at"]


def test_insufficient_statistics_no_verdict():
    assert block_interval([.01] * 6)["low"] is None
    assert "insufficient" in deflated_sharpe(.1, 6, 1)["status"].lower()
    assert "required" in deflated_sharpe(.1, 30, 5)["status"].lower()
    values = np.random.default_rng(42).normal(0, .01, 40)
    assert block_interval(values) == block_interval(values)


def test_ninjatrader_export_fraction_and_unknown():
    raw = b"20260803 133000 1234567;5600.25;2\n"
    frame = ninjatrader(raw, "ESU6")
    assert frame.ts.iloc[0] == T + pd.Timedelta(nanoseconds=123456700)
    assert frame.side.iloc[0] == "unknown"
    with pytest.raises(ValueError):
        ninjatrader(b"20260803;5600;5601;5599;5600;10", "ESU6")


def test_canonical_availability_cannot_precede_event():
    frame = market([trade()])
    frame["available_at"] = T - pd.Timedelta(seconds=1)
    with pytest.raises(ValueError, match="availability"):
        canonical(frame.to_csv(index=False).encode(), "ticks.csv", "market", "UTC", "event")
