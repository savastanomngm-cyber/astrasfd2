# Γ Gamma Lab — Order-Flow Research Terminal

**Causal research terminal for ES/NQ futures.** Combines tick-level order-flow analysis with point-in-time options gamma exposure to test location-based hypotheses under walk-forward evaluation.

> Historical research only. No live feed. No order routing. No profitability claims. Local-first by design.

---

## What it does

1. **Import futures tick data** — Canonical CSV/Parquet, NinjaTrader tick text, Databento trades CSV
2. **Import options snapshots** — Strike-level OI with explicit publication timestamps
3. **Classify trades** — Causal quote-side inference for unknown aggressors
4. **Build footprint charts** — 60-second bars with delta, volume, classified-fraction
5. **Compute gamma Greeks** — Black-76 via QuantLib, gamma-dollar concentration
6. **Test four hypotheses** — Price baseline, gamma location, footprint, gamma+footprint
7. **Walk-forward evaluation** — Rolling training/out-of-sample splits, reserved holdout
8. **Execution simulation** — Latency, slippage, quote aging, session loss halts
9. **Stress scenarios** — Replay signals under varying costs without retuning
10. **Trade journal** — Persistent SQLite registry with exportable audit bundles

---

## Quick start

### macOS (double-click)

Double-click `Start Gamma Lab.command`. First launch installs dependencies (needs internet).

### Terminal

```bash
python3 launch.py
```

Open http://localhost:8501.

### Docker

```bash
docker compose up --build
```

### Load the tutorial

Click **"Explore with synthetic data"** → **"Load synthetic tutorial"** in the Data workspace. Generates a 6-session deterministic synthetic dataset.

---

## Importing your data

| Format | Streams | Notes |
|---|---|---|
| Canonical CSV/Parquet | trade, quote, bid, ask, options | Schema templates in Data workspace |
| NinjaTrader tick text | Last, Bid, Ask | 3-field tick or 5-field tick-replay |
| Databento trades CSV | trades only | Pretty timestamps, decimal prices |

- Options require explicit OI publication timestamps
- European-style only; American contracts excluded from Black-76
- 100 MB / 2M records per import
- Overlapping sources for same contract/stream are rejected

---

## Architecture

```
├── launch.py                # Launcher with venv bootstrapping
├── terminal.py              # Streamlit app entry point
├── gamma_lab/               # Core engine (16 modules)
│   ├── data_screen.py       # Import UI & source management
│   ├── evaluation.py        # Walk-forward experiment orchestration
│   ├── execution.py         # Trade simulation engine
│   ├── importers.py         # Canonical, NinjaTrader, Databento parsers
│   ├── models.py            # Contract specs, RunConfig
│   ├── options.py           # Black-76, Greeks, gamma concentration
│   ├── orderflow.py         # Classification, footprint, quote book, OFI
│   ├── replay_screen.py     # Cursor-driven replay & options map
│   ├── research.py          # Walk-forward logic
│   ├── research_screen.py   # Research, journal, stress UI
│   ├── setups.py            # Zone detection & signal generation
│   ├── statistics.py        # Block intervals, deflated Sharpe
│   ├── storage.py           # SQLite + Parquet + DuckDB persistence
│   ├── tutorial.py          # Seeded synthetic data generator
│   └── visuals.py           # Plotly charts & Streamlit styling
├── tests/
│   ├── test_terminal.py     # Streamlit integration tests
│   ├── test_invariants.py   # Engine invariants & property tests
│   └── test_repairs.py      # Recovery & edge-case tests
├── app/                     # Next.js frontend
├── data/                    # Local storage (gitignored)
└── requirements.txt
```

---

## Key design decisions

- **Point-in-time everywhere.** `known_rows()` clips data at the cursor. Holdout data is cryptographically invisible to training.
- **Immutable sources.** Every import is SHA-256 hashed. Engine files are hashed and recorded in every trial.
- **No silent decisions.** Overlapping sources rejected. Off-tick prices rejected. Ambiguous quotes invalidated. Every exclusion is auditable.

---

## Testing

```bash
python3 -m pytest tests/ -q
```

---

## License

MIT — see [LICENSE](./LICENSE).
