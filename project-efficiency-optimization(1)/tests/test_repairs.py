import io
import json
import zipfile

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import gamma_lab.storage as storage
from gamma_lab.importers import validate
from gamma_lab.research_screen import archive_run
from tests.test_terminal import ROOT, find


def quotes(days):
    rows = []
    for day in days:
        ts = pd.Timestamp(f"2026-08-{day:02d}T13:30:00Z")
        rows.append(dict(ts=ts, available_at=ts, contract="ESU6", kind="quote", price=5600.125, size=0, bid=5600., ask=5600.25))
    return validate(pd.DataFrame(rows), "market")


def add_source(store, days):
    frame = quotes(days)
    return store.add(frame.to_csv(index=False).encode(), frame, "market", {"synthetic": True})


def test_missing_partition_blocks_partial_research(tmp_path):
    store = storage.Store(tmp_path)
    source = add_source(store, [3, 4])
    next((tmp_path / "sources" / source).glob("*/*/*.parquet")).unlink()
    with pytest.raises(ValueError, match="[Ii]ncomplete"):
        store.load([source])


def test_completely_missing_source_is_not_empty_input(tmp_path):
    store = storage.Store(tmp_path)
    source = add_source(store, [3])
    next((tmp_path / "sources" / source).glob("*/*/*.parquet")).unlink()
    with pytest.raises(ValueError, match="[Ii]ncomplete"):
        store.load([source])
    assert store.load([]).empty


def test_duplicate_selection_does_not_duplicate_records(tmp_path):
    store = storage.Store(tmp_path)
    source = add_source(store, [3, 4])
    assert len(store.load([source, source])) == 2


@pytest.mark.parametrize("failure", ["broken-library", "wrong-platform"])
def test_launcher_repairs_unusable_environment(tmp_path, monkeypatch, failure):
    import launch
    from types import SimpleNamespace

    monkeypatch.setattr(launch, "__file__", str(tmp_path / "launch.py"))
    monkeypatch.setattr(launch.sys, "argv", ["launch.py", "--setup"])
    monkeypatch.chdir(tmp_path)
    environment = tmp_path / ".venv"
    interpreter = environment / ("Scripts/python.exe" if launch.os.name == "nt" else "bin/python")
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    (tmp_path / "requirements.txt").write_text("streamlit>=1.49,<2\n")
    calls = []

    def probe(*args, **kwargs):
        if failure == "wrong-platform":
            raise OSError("Exec format error")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(launch.subprocess, "run", probe)
    monkeypatch.setattr(launch.subprocess, "check_call", lambda args: calls.append(args))
    launch.main()
    assert calls[0][1:3] == ["-m", "venv"]
    assert calls[1][1:4] == ["-m", "pip", "install"]
    assert (environment / ".requirements-sha256").exists()


def test_replay_session_resets_after_source_switch(tmp_path, monkeypatch):
    original = storage.Store
    monkeypatch.setattr(storage, "Store", lambda: original(tmp_path))
    first = add_source(original(tmp_path), [3, 4])
    second = add_source(original(tmp_path), [5, 6])
    app = AppTest.from_file(str(ROOT / "terminal.py"), default_timeout=90)
    app.session_state["source_ids"] = [first]
    app.run()
    app.radio(key="screen").set_value("Synchronized replay").run()
    assert find(app.selectbox, "Replay session · Chicago trading date").value == "2026-08-03"
    app.multiselect(key="source_ids").set_value([second]).run()
    assert not app.exception
    assert find(app.selectbox, "Replay session · Chicago trading date").value == "2026-08-05"


def test_removed_source_selection_does_not_crash(tmp_path, monkeypatch):
    original = storage.Store
    monkeypatch.setattr(storage, "Store", lambda: original(tmp_path))
    app = AppTest.from_file(str(ROOT / "terminal.py"), default_timeout=90)
    app.session_state["source_ids"] = ["no-longer-registered"]
    app.run()
    assert not app.exception
    assert app.multiselect(key="source_ids").value == []


def test_single_session_disables_research(tmp_path, monkeypatch):
    original = storage.Store
    monkeypatch.setattr(storage, "Store", lambda: original(tmp_path))
    source = add_source(original(tmp_path), [3])
    app = AppTest.from_file(str(ROOT / "terminal.py"), default_timeout=90)
    app.session_state["source_ids"] = [source]
    app.run()
    app.radio(key="screen").set_value("Research").run()
    assert not app.exception
    assert find(app.button, "Run walk-forward comparison").disabled
    assert find(app.button, "Evaluate final holdout").disabled


def test_audit_bundle_contains_persisted_manifest_and_tables(tmp_path):
    store = storage.Store(tmp_path)
    run = store.register({"phase": "development", "sources": ["example"]}, {"status": "complete"})
    trades = pd.DataFrame([{"net_pnl": -5., "quantity": 1}])
    store.save_artifacts(run, {"baseline_trades": trades})
    restored = storage.Store(tmp_path)
    row = restored.runs().iloc[0].to_dict()
    with zipfile.ZipFile(io.BytesIO(archive_run(restored, run, row))) as archive:
        assert set(archive.namelist()) == {"manifest.json", "baseline_trades.csv"}
        assert json.loads(archive.read("manifest.json"))["id"] == run
        pd.testing.assert_frame_equal(pd.read_csv(archive.open("baseline_trades.csv")), trades)
