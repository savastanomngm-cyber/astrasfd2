from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
from importlib.metadata import version

from gamma_lab import __version__

import duckdb
import pandas as pd
import polars as pl

from gamma_lab.importers import audit
from gamma_lab.models import digest

ROOT = Path(__file__).resolve().parents[1] / "data"


class Store:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "registry.sqlite"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, kind TEXT, metadata TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created TEXT, config TEXT, result TEXT, holdout INTEGER)")
            db.execute("CREATE TABLE IF NOT EXISTS studies (id TEXT PRIMARY KEY, manifest TEXT NOT NULL, opened_at TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS exposures (contract TEXT, session TEXT, first_seen TEXT, PRIMARY KEY(contract, session))")

    def connect(self):
        return sqlite3.connect(self.database)

    def add(self, raw: bytes, frame: pd.DataFrame, kind: str, metadata: dict) -> str:
        raw_hash = hashlib.sha256(raw).hexdigest()
        source_id = digest({"raw": raw_hash, "kind": kind, "import": metadata})
        folder = self.root / "sources" / source_id
        folder.mkdir(parents=True, exist_ok=True)
        info = {**metadata, "raw_sha256": raw_hash, "audit": audit(frame, kind), "imported_at": datetime.now(timezone.utc).isoformat()}
        with self.connect() as db:
            if db.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
                return source_id
            (folder / "original.bin").write_bytes(raw)
            frame = frame.copy()
            frame["source_id"] = source_id
            for (symbol, date), group in frame.groupby(["contract", frame.ts.dt.strftime("%Y-%m-%d")]):
                partition = folder / symbol.replace(" ", "_") / date
                partition.mkdir(parents=True, exist_ok=True)
                pl.from_pandas(group).write_parquet(partition / "records.parquet")
            (folder / "manifest.json").write_text(json.dumps(info, default=str, indent=2), encoding="utf-8")
            db.execute("INSERT INTO sources VALUES (?, ?, ?)", (source_id, kind, json.dumps(info, default=str)))
        return source_id

    def sources(self):
        with self.connect() as db:
            return [dict(id=i, kind=k, **json.loads(m)) for i, k, m in db.execute("SELECT id,kind,metadata FROM sources")]

    def load(self, source_ids: list[str]) -> pd.DataFrame:
        allowed = {s["id"]: s for s in self.sources()}
        if any(s not in allowed for s in source_ids):
            raise ValueError("Unknown source selection.")
        if not source_ids:
            return pd.DataFrame()
        source_ids = list(dict.fromkeys(source_ids))
        files = [str(p) for s in source_ids for p in (self.root / "sources" / s).glob("*/*/*.parquet")]
        incomplete = "Incomplete source data. Restore the full data folder from your backup before running research."
        if not files:
            raise ValueError(incomplete)
        with duckdb.connect() as db:
            frame = db.execute("SELECT * FROM read_parquet(?, union_by_name=true) ORDER BY ts, sequence", [files]).df()
        if "source_id" not in frame:
            raise ValueError(incomplete)
        counts = frame.groupby("source_id").size().to_dict()
        expected = {s: allowed[s]["audit"]["records"] for s in source_ids}
        if counts != expected:
            raise ValueError(incomplete)
        return frame

    def study(self, source_ids, symbol, days):
        manifest = {"sources": sorted(source_ids), "contract": symbol, "sessions": sorted(days), "holdout": sorted(days)[-1:], "policy": "last-session-v1"}
        study_id = digest(manifest)
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO studies VALUES (?, ?, NULL)", (study_id, json.dumps(manifest)))
            opened = db.execute("SELECT opened_at FROM studies WHERE id=?", (study_id,)).fetchone()[0]
            exposed = [d for d in manifest["holdout"] if db.execute("SELECT 1 FROM exposures WHERE contract=? AND session=?", (symbol, d)).fetchone()]
        return {"id": study_id, **manifest, "opened_at": opened, "previously_exposed": exposed}

    def record_exposure(self, symbol, days):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.executemany("INSERT OR IGNORE INTO exposures VALUES (?, ?, ?)", [(symbol, d, now) for d in days])

    def open_holdout(self, study_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT manifest FROM studies WHERE id=?", (study_id,)).fetchone()
            if not row:
                raise ValueError("Unknown study.")
            manifest = json.loads(row[0])
            now = datetime.now(timezone.utc).isoformat()
            db.execute("UPDATE studies SET opened_at=COALESCE(opened_at, ?) WHERE id=?", (now, study_id))
            db.executemany("INSERT OR IGNORE INTO exposures VALUES (?, ?, ?)", [(manifest["contract"], d, now) for d in manifest["holdout"]])

    def save_artifacts(self, run_id, tables):
        if not run_id.isalnum():
            raise ValueError("Invalid run identifier.")
        folder = self.root / "runs" / run_id
        folder.mkdir(parents=True, exist_ok=True)
        for name, frame in tables.items():
            if not name.replace("_", "").isalnum():
                raise ValueError("Invalid table name.")
            frame.to_parquet(folder / f"{name}.parquet", index=False)

    def artifacts(self, run_id):
        if not run_id.isalnum():
            raise ValueError("Invalid run identifier.")
        return {p.stem: pd.read_parquet(p) for p in (self.root / "runs" / run_id).glob("*.parquet")}

    def register(self, config: dict, result: dict, holdout=False) -> str:
        run_id = uuid.uuid4().hex[:12]
        engine_files = ["models", "execution", "orderflow", "options", "setups", "statistics", "research", "evaluation", "importers"]
        engine_hash = hashlib.sha256(b"".join((Path(__file__).parent / f"{name}.py").read_bytes() for name in engine_files)).hexdigest()
        dependencies = {name: version(name) for name in ["numpy", "pandas", "scipy", "QuantLib", "duckdb", "polars"]}
        payload = {**config, "config_hash": digest(config), "engine_version": __version__, "engine_sha256": engine_hash, "dependencies": dependencies}
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?)", (run_id, datetime.now(timezone.utc).isoformat(), json.dumps(payload, default=str), json.dumps(result, default=str), int(holdout)))
        return run_id

    def complete_run(self, run_id, result):
        with self.connect() as db:
            db.execute("UPDATE runs SET result=? WHERE id=?", (json.dumps(result, default=str), run_id))

    def runs(self):
        with self.connect() as db:
            return pd.read_sql_query("SELECT * FROM runs ORDER BY created DESC", db)


def reject_overlapping_sources(frame: pd.DataFrame):
    if frame.empty or "source_id" not in frame:
        return
    group_cols = ["contract", "kind"] if "kind" in frame else ["contract"]
    for _, group in frame.groupby(group_cols):
        spans = group.groupby("source_id").ts.agg(["min", "max"]).sort_values("min")
        if len(spans) > 1 and (spans['min'].iloc[1:].to_numpy() <= spans['max'].cummax().iloc[:-1].to_numpy()).any():
            raise ValueError("Overlapping sources for the same contract/stream. Select only one export for overlapping periods; no silent deduplication.")
