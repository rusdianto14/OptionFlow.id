# OptionFlow.id — Math Verification

## Status

- **Tests**: 111 unit tests pass (2 skipped: deep-OTM where price collapses below numerical floor — expected).
- **Lint**: ruff clean.
- **Manual verification**: engine output for K=7250 matches hand-computed GEX exactly to all reported digits.
- **End-to-end**: live Databento OPRA.PILLAR -> definitions + statistics + cbbo-1m + ohlcv-1m
  → ChainSnapshot → GEX, ZeroGamma, Walls all working.

## Snapshot used

- **Underlying**: SPXW, NDXP (0DTE)
- **Trade date**: 2026-05-01 (Friday, last RTH session before today)
- **Snapshot UTC**: 2026-05-01 18:00 (= 14:00 ET, mid-RTH, 2 hours from close)
- **r**: 4.30%, **q_SPX**: 1.30%, **q_NDX**: 0.70%

## SPXW result

```
Strikes total        : 348 (1600-9200; only ~80 within ±2% of F)
T (years)            : 0.000228  (2.00 hours)
Synthetic forward F  : 7251.8021
Spot implied         : 7251.7524

Zero gamma           : 7248.90
  bracket            : [7245.00, 7260.00] (between major short / major long by volume)
  in_bracket         : True   <-- constraint satisfied
Call Wall            : 7340 (OI 30715)
Put Wall             : 5300 (OI 47359)   <-- see note below

Major long GEX (top 3 by VOLUME):
  K=7260   gex=+9.167e+10
  K=7265   gex=+5.820e+10
  K=7270   gex=+5.676e+10
Major short GEX (top 3 by VOLUME):
  K=7240   gex=-5.851e+10
  K=7245   gex=-3.974e+10
  K=7235   gex=-3.878e+10
```

## NDXP result

```
Strikes total        : 411 (12000-35500)
Synthetic forward F  : 27758.2491

Zero gamma           : 27677.96
  bracket            : [27640.00, 27800.00]   <-- constraint satisfied
Call Wall            : 27910 (OI 151)
Put Wall             : 22000 (OI 7613)

Major long GEX (top 3 by VOLUME):  K=27800/27820/27750
Major short GEX (top 3 by VOLUME): K=27600/27500/27640
```

## Manual verification at K=7250 SPXW

Recomputed by hand from raw inputs to prove the engine isn't fudging:

```
F           = 7251.8021
K           = 7250.00
T           = 2.0 hours / (365 × 24) = 2.283e-04 years
sigma       = 0.1195    (smile-aware IV at K=7250)
r, q        = 4.30%, 1.30%
OI_call     = 6813
OI_put      = 404
Vol_call    = 74,750
Vol_put     = 84,478

BSM gamma(S=F, K=7250, T, r, q, sigma) = 3.0157e-02
multiplier = 100 × F² × 0.01 = 5.2589e+07

GEX-by-OI   = γ × (OI_call - OI_put) × mult
            = 3.0157e-02 × (6813 - 404) × 5.2589e+07
            = +1.0164e+10        ← matches engine output
GEX-by-Vol  = γ × (vol_call - vol_put) × mult
            = 3.0157e-02 × (74750 - 84478) × 5.2589e+07
            = -1.5428e+10        ← matches engine output
```

## Methodology

### 1. BSM Greeks (greeks.py)

Generalized Black-Scholes-Merton with continuous dividend yield q.

```
d1 = [ln(S/K) + (r - q + σ²/2)T] / (σ√T)
d2 = d1 - σ√T
gamma = e^(-qT) × φ(d1) / (S·σ·√T)
```

Validated:
- Put-call parity: C − P = S·e^(-qT) − K·e^(-rT)  (multiple ATM/OTM strikes)
- Hull 10e textbook reference values (call/put price + delta examples)
- Numerical derivatives match analytical Greeks to 10⁻⁴
- Edge cases: T=0 intrinsic, sigma=0 deterministic forward, far-OTM gamma → 0

### 2. Implied Volatility solver (implied_vol.py)

Newton-Raphson with vega derivative + Brent's method fallback.
- Sanity checks no-arbitrage bounds (intrinsic ≤ price ≤ S·e^(-qT) for calls)
- Returns NaN on invalid inputs (negative price, T=0, price outside bounds)
- `mid_price` filter rejects: zero/negative bid or ask, ask ≤ bid, spread > 50% of mid

Validated:
- Roundtrip (price → solve sigma → reprice) accurate to 10⁻⁴ across smile (0.05–1.20 vol, ITM/ATM/OTM)
- 0DTE specific: T = 0.25h to 6h, ATM and ±0.5% offsets all converge

### 3. Synthetic Forward (synthetic_forward.py)

Put-call parity gives: F = (C_mid − P_mid) × e^(rT) + K. Per-strike F_K candidates
are robust-aggregated: take median across all valid pairs to anchor, then weighted-average
the 10 most-ATM candidates (weights ∝ 1/distance-to-anchor).

Validated:
- Clean BSM quotes recover F to 10⁻⁶ accuracy
- With 1c noise on mids, F still within 1 bp
- With smile (different sigma per strike), F still recovers (parity is sigma-independent)
- Handles missing quotes (NaN, negative bid, etc.) by filtering

### 4. GEX (compute.py)

Per strike: `gex(K) = γ(K) × (Q_call(K) − Q_put(K)) × 100 × S² × 0.01`
where Q is OI or Volume. Sign convention matches SpotGamma / GEXBOT public docs:
positive GEX → dealer long gamma (mean-reverting), negative → short gamma (volatile).

Implementation detail: per-strike IV is taken **smile-aware** — for K < F use OTM put IV
(call mid is dominated by intrinsic and is noisy), for K > F use OTM call IV. This is
the theoretically clean choice because BSM call IV equals BSM put IV at the same strike;
any difference is just quote noise.

### 5. Major Long / Short GEX

Top N strikes (configurable 1..5, default 3) by **volume-based** GEX, sign-separated.

### 6. Zero Gamma (root finding with constraint)

Compute `g(S') = Σ γ(S', K) × (Q_call − Q_put)` (excluding the positive S'² multiplier
which is monotonic). Find S' where g(S') = 0 via Brent's method.

**Constraint** (your spec): bracket = [highest major-short strike below F, lowest major-long
strike above F], both by volume. If a sign change exists in this bracket, root is inside.

Fallbacks (in order):
1. Widen bracket by ±10% (logged)
2. Scan full strike range
3. Return NaN if no sign change anywhere (logged)

### 7. Put / Call Walls

- Call Wall: strike with maximum call OI strictly above F.
- Put Wall: strike with maximum put OI strictly below F.

**Note on SPXW Put Wall = 5300**: this is the literal max-OI put below F (47k contracts at
27% OTM, deep crash hedges with zero gamma today). Following your spec ("by OI bodoamat,
terserah kamu"). Three options if this isn't desired:
  (a) Keep it (current behaviour) — exactly your spec.
  (b) Restrict wall search to ±N% of F (e.g. ±5%) → would pick K=6975 (OI 9879) for SPXW.
  (c) Use put GEX-by-OI (gamma-weighted) → naturally near F.

Tell me which you prefer; the change is one line.

## Files & how to reproduce

```
src/optionflow/greeks.py            # 26 unit tests
src/optionflow/implied_vol.py       # 68 unit tests (66 pass + 2 OTM skips)
src/optionflow/synthetic_forward.py #  7 unit tests
src/optionflow/compute.py           # 12 unit tests
src/optionflow/databento_loader.py  # historical loader for SPXW.OPT / NDXP.OPT

scripts/snapshot_cli.py             # CLI: pull chain, compute, dump CSV
scripts/manual_verify.py            # CLI: hand-recompute GEX at one strike

# reproduce
uv run pytest                                    # all tests
uv run python scripts/snapshot_cli.py --underlying SPXW --date 2026-05-01 --time 14:00
uv run python scripts/snapshot_cli.py --underlying NDXP --date 2026-05-01 --time 14:00
uv run python scripts/manual_verify.py --csv snapshot_SPXW_*.csv --strike 7250 --F 7251.80 --T-hours 2.0
```

## What to verify against external reference

The CSVs include per-strike: `iv_call iv_put oi_call oi_put vol_call vol_put gex_oi gex_volume`.
You can:
1. Cross-check raw OI/Volume vs broker chain or GEXBOT panel.
2. Pick any strike, plug into the manual_verify formula above.
3. Compare F vs CME ES / NQ futures price at 14:00 ET on 2026-05-01.
4. Compare ZG / Major GEX strikes vs SpotGamma/GEXBOT screenshots if available.
