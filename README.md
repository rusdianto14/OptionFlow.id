# OptionFlow.id

0DTE options-flow analytics engine for **SPXW** & **NDXP**, fed by Databento OPRA.PILLAR
and served (eventually) to **MotiveWave** and **ATAS** indicators.

Computes per minute:

- **GEX** (Gamma Exposure) per strike, by Open Interest and by Volume
- **Zero Gamma** (constrained root between major-volume short and major-volume long strikes)
- **Major Long / Short GEX** (top N strikes by volume, default N=3, configurable 1–5)
- **Call Wall** / **Put Wall** (max OI on each side of the synthetic forward)
- **Synthetic Forward F** via put-call parity regression (clients shift to ES/NQ live)

Status: math engine validated end-to-end. See [VERIFICATION.md](./VERIFICATION.md).
Now also includes Postgres + FastAPI service for serving snapshots to indicators.

## Install

```bash
# from project root
uv sync --extra dev
```

## Configuration

Copy `.env.example` to `.env` and fill in:

```bash
DATABENTO_API_KEY=db-...                                         # required
DATABASE_URL=postgresql+psycopg://optionflow:optionflow@localhost:5432/optionflow
OPTIONFLOW_API_KEY=...                                           # required for /levels endpoint

# Optional (defaults shown)
OPTIONFLOW_R=0.0430                          # SOFR / 3M T-bill (continuous)
OPTIONFLOW_Q_SPX=0.0130                      # SPX dividend yield
OPTIONFLOW_Q_NDX=0.0070                      # NDX dividend yield
OPTIONFLOW_N_MAJOR=3                         # top-N major long/short (1..5)
OPTIONFLOW_SNAPSHOT_INTERVAL_SECONDS=60      # writer poll interval
OPTIONFLOW_LOG_LEVEL=INFO
```

## Quick start (full stack, local)

```bash
# 1. Bring up Postgres
docker compose up -d

# 2. Write a snapshot for an offline date (or run loop while market is open)
uv run python scripts/run_writer.py once --underlying SPXW --underlying NDXP \
    --date 2026-05-01 --time 14:00

# 3. Start the API
uv run python scripts/run_api.py --port 8000

# 4. Query the API
curl -H "X-API-Key: $OPTIONFLOW_API_KEY" http://localhost:8000/levels/SPXW
```

To run the writer in a forever loop (RTH only, while market is open):

```bash
uv run python scripts/run_writer.py loop --underlying SPXW --underlying NDXP
```

## API

| Method | Path                  | Auth          | Description                      |
| ------ | --------------------- | ------------- | -------------------------------- |
| GET    | `/health`             | none          | Liveness probe                   |
| GET    | `/levels/{underlying}` | `X-API-Key`   | Latest snapshot for `SPXW`/`NDXP` |

Response shape (`/levels/SPXW`):

```json
{
  "underlying": "SPXW",
  "computed_at": "2026-05-01T18:00:00Z",
  "expiration": "2026-05-01",
  "f_synth": 7251.80,
  "spot_implied": 7251.75,
  "zero_gamma": {"value": 7248.89, "in_bracket": true, "fallback_used": false, "note": null},
  "call_wall": {"strike": 7340, "oi": 30715},
  "put_wall":  {"strike": 5300, "oi": 47359},
  "n_major": 3,
  "major_long_gex":  [{"strike": 7260, "gex": 9.17e10, "by": "volume"}, ...],
  "major_short_gex": [{"strike": 7240, "gex": -5.85e10, "by": "volume"}, ...],
  "diagnostics": {"total_gex_volume": ..., "total_gex_oi": ...}
}
```

Indicator clients should:

1. Poll `/levels/{underlying}` every 60 s.
2. Read `F_live` from their own datafeed (Rithmic / CQG ES or NQ).
3. Compute `basis = F_live − f_synth` and shift each strike by `basis` before plotting.

## Other CLI tools

```bash
# Stand-alone debug snapshot (no DB) -> CSV dump for manual inspection
uv run python scripts/snapshot_cli.py --underlying SPXW --date 2026-05-01 --time 14:00

# Manual hand-check at one strike
uv run python scripts/manual_verify.py \
  --csv snapshot_SPXW_2026-05-01_1400.csv \
  --strike 7250 --F 7251.80 --T-hours 2.0
```

## Run tests

```bash
docker compose up -d           # tests use the local Postgres for DB / API tests
uv run pytest -v
uv run ruff check .
```

## Layout

```
src/optionflow/
  greeks.py              # BSM Greeks (delta, gamma, vega, theta) — vectorized
  implied_vol.py         # Newton-Raphson IV solver + Brent fallback
  synthetic_forward.py   # Put-call parity forward regression
  compute.py             # GEX, Zero Gamma (constrained), Put/Call Walls
  databento_loader.py    # OPRA.PILLAR ingest primitives
  pipeline.py            # End-to-end pull + build chain orchestration
  config.py              # pydantic-settings env-var loader
  db.py                  # SQLAlchemy 2.x ORM (levels_latest)
  snapshot_writer.py     # Pull -> compute -> UPSERT (one-shot or loop)
  api.py                 # FastAPI service /levels/{underlying}

scripts/
  snapshot_cli.py        # Stand-alone CSV dump (no DB)
  manual_verify.py       # Per-strike hand-recompute for spot checks
  probe_api.py           # Smoke-test Databento credentials & schema access
  run_writer.py          # Snapshot writer CLI (once / loop)
  run_api.py             # FastAPI server CLI (uvicorn wrapper)

tests/
  test_greeks.py             # 26 tests
  test_implied_vol.py        # 68 tests
  test_synthetic_forward.py  #  7 tests
  test_compute.py            # 12 tests
  test_db.py                 #  5 tests (DB UPSERT, NaN -> NULL)
  test_api.py                #  7 tests (auth, 404, response shape)
```

## Methodology

Per-strike GEX (matches SpotGamma / GEXBOT public docs):

```
gex(K) = γ(K) × ( Q_call(K) − Q_put(K) ) × 100 × F² × 0.01
```

where Q ∈ {OI, Volume}; γ from generalized BSM with continuous q.

Zero Gamma:

```
g(S') = Σ_K γ(S', K) × ( Q_call(K) − Q_put(K) )
```

Brent root finder on `g(S') = 0`, **constrained** between the closest major-volume
short strike below F and major-volume long strike above F. Fallbacks: widen ±10% then
full strike range.

See [VERIFICATION.md](./VERIFICATION.md) for derivations, references, and snapshot examples.

## Roadmap

- [x] BSM Greeks + tests
- [x] IV solver
- [x] Synthetic forward
- [x] GEX / ZG / Walls compute
- [x] Databento historical loader + CLI
- [x] Postgres schema + REST API (FastAPI, `/levels/{underlying}`)
- [ ] Cloudflare Tunnel for public access
- [ ] MotiveWave Study (Java SDK)
- [ ] ATAS Indicator (C# .NET)
