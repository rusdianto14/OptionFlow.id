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

## Install

```bash
# from project root
uv sync --extra dev
```

## Configuration

```bash
export DATABENTO_API_KEY=db-...   # required for Databento ingest
```

Defaults (configurable):

```
r       = 0.0430        # SOFR / 3M T-bill (continuous)
q_SPX   = 0.0130        # SPX dividend yield (continuous)
q_NDX   = 0.0070        # NDX dividend yield (continuous)
n_major = 3             # top-N strikes for major long / short GEX (1..5)
```

## Usage

### CLI debug snapshot (historical)

```bash
# SPXW 0DTE snapshot at 14:00 ET on 2026-05-01
uv run python scripts/snapshot_cli.py --underlying SPXW --date 2026-05-01 --time 14:00

# NDXP 0DTE
uv run python scripts/snapshot_cli.py --underlying NDXP --date 2026-05-01 --time 14:00 --r 0.043 --q 0.007
```

Outputs:
- Console summary (forward, ZG, Walls, Major GEX)
- `snapshot_<underlying>_<date>_<time>.csv` — per-strike `iv, oi, vol, gex_oi, gex_volume`

### Manual hand-check at one strike

```bash
uv run python scripts/manual_verify.py \
  --csv snapshot_SPXW_2026-05-01_1400.csv \
  --strike 7250 --F 7251.80 --T-hours 2.0
```

Recomputes GEX from raw inputs and compares against engine output digit-for-digit.

### Run unit tests

```bash
uv run pytest -v
```

## Layout

```
src/optionflow/
  greeks.py              # BSM Greeks (delta, gamma, vega, theta) — vectorized
  implied_vol.py         # Newton-Raphson IV solver + Brent fallback
  synthetic_forward.py   # Put-call parity forward regression
  compute.py             # GEX, Zero Gamma (constrained), Put/Call Walls
  databento_loader.py    # OPRA.PILLAR ingest (definition / statistics / cbbo-1m / ohlcv-1m)

scripts/
  snapshot_cli.py        # Pull chain + compute snapshot + CSV dump
  manual_verify.py       # Per-strike hand-recompute for spot checks
  probe_api.py           # Smoke-test Databento credentials & schema access

tests/
  test_greeks.py             # 26 tests (Hull reference, parity, numerical Greeks, edge cases)
  test_implied_vol.py        # 68 tests (roundtrip across smile, 0DTE, edge cases)
  test_synthetic_forward.py  #  7 tests (clean recovery, noise, smile, missing quotes)
  test_compute.py            # 12 tests (GEX, ZG constraint, Walls, end-to-end)
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
- [ ] Postgres schema + REST API (FastAPI, `/levels/{underlying}`)
- [ ] Cloudflare Tunnel for public access
- [ ] MotiveWave Study (Java SDK)
- [ ] ATAS Indicator (C# .NET)
