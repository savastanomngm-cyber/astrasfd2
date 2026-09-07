from pathlib import Path

from streamlit.testing.v1 import AppTest
import pytest

import gamma_lab.storage as storage


ROOT = Path(__file__).resolve().parents[1]


def find(elements, label):
    return next(element for element in elements if element.label == label)


def test_empty_workspace_and_blocked_research(tmp_path, monkeypatch):
    original = storage.Store
    monkeypatch.setattr(storage, "Store", lambda: original(tmp_path))
    app = AppTest.from_file(str(ROOT / "terminal.py"), default_timeout=90).run()
    assert not app.exception
    assert "Good research" in app.title[0].value
    app.radio(key="screen").set_value("Research").run()
    assert not app.exception
    assert any("Missing inputs disable" in message.value for message in app.info)
    app.radio(key="screen").set_value("Trade journal").run()
    assert not app.exception
    assert any("No registered trials" in message.value for message in app.info)


def test_quote_only_replay_shows_missing_trades(tmp_path, monkeypatch):
    import pandas as pd
    from gamma_lab.importers import validate

    original = storage.Store
    monkeypatch.setattr(storage, "Store", lambda: original(tmp_path))
    records = []
    for time in ["2026-08-03T13:30:00Z", "2026-08-04T13:30:00Z"]:
        t = pd.Timestamp(time)
        records.append(dict(ts=t, available_at=t, contract="ESU6", kind="quote", price=5600.125, size=0, bid=5600., ask=5600.25))
    frame = validate(pd.DataFrame(records), "market")
    ident = original(tmp_path).add(frame.to_csv(index=False).encode(), frame, "market", {"synthetic": True})
    app = AppTest.from_file(str(ROOT / "terminal.py"), default_timeout=90)
    app.session_state["source_ids"] = [ident]
    app.run()
    app.radio(key="screen").set_value("Synchronized replay").run()
    assert not app.exception
    assert any("No executed trades" in message.value for message in app.info)


@pytest.mark.parametrize("symbol", ["ESU6", "NQU6"])
def test_tutorial_replay_research_and_persistent_journal(tmp_path, monkeypatch, symbol):
    original = storage.Store
    monkeypatch.setattr(storage, "Store", lambda: original(tmp_path))
    app = AppTest.from_file(str(ROOT / "terminal.py"), default_timeout=120).run()
    find(app.selectbox, "Tutorial contract").set_value(symbol).run()
    find(app.button, "Load synthetic tutorial").click().run()
    assert not app.exception
    assert not app.error
    assert len(original(tmp_path).sources()) == 2
    assert any("SYNTHETIC TUTORIAL" in message.value for message in app.warning)
    for screen in ["Options map", "Synchronized replay"]:
        app.radio(key="screen").set_value(screen).run()
        assert not app.exception
        assert not app.error
        assert "2026-08-10" not in find(app.selectbox, "Replay session · Chicago trading date").options
    app.radio(key="screen").set_value("Research").run()
    assert not app.exception
    assert find(app.button, "Evaluate final holdout").disabled
    find(app.button, "Run walk-forward comparison").click().run()
    assert not app.exception
    assert not app.error
    assert len(original(tmp_path).runs()) > 1
    find(app.button, "Run execution stress scenarios").click().run()
    assert not app.exception
    assert not app.error
    app.radio(key="screen").set_value("Trade journal").run()
    assert not app.exception
    assert len(app.dataframe) >= 1
    app.radio(key="screen").set_value("Research").run()
    find(app.checkbox, "I understand opening the holdout permanently marks it as exposed").check().run()
    find(app.button, "Evaluate final holdout").click().run()
    assert not app.exception
    assert not app.error
    app.radio(key="screen").set_value("Synchronized replay").run()
    assert "2026-08-10" in find(app.selectbox, "Replay session · Chicago trading date").options
    assert not app.exception
