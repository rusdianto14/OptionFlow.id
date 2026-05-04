"""CLI debug tool: pull a 0DTE chain snapshot from Databento, compute everything,
print summary, and dump per-strike data to CSV for manual verification.

Usage:
    uv run python scripts/snapshot_cli.py --underlying SPXW --date 2026-05-01 --time 14:00
    uv run python scripts/snapshot_cli.py --underlying NDXP --date 2026-05-01 --time 14:00 --r 0.043 --q 0.007
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

import databento as db
import numpy as np
import pandas as pd

# allow running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from optionflow import compute, databento_loader  # noqa: E402

# Default config for 0DTE compute
DEFAULT_R = 0.043  # SOFR / 3M T-bill approx (May 2026)
DEFAULT_Q = {"SPXW": 0.013, "SPX": 0.013, "NDX": 0.007, "NDXP": 0.007}

# Underlying -> parent symbol on Databento
PARENT_SYMBOL = {"SPXW": "SPXW.OPT", "NDX": "NDX.OPT", "NDXP": "NDXP.OPT", "SPX": "SPX.OPT"}

# RTH session close UTC for SPX/NDX index options:
# SPX/SPXW PM-settled close at 16:15 ET = 20:15 UTC (during DST). NDX/NDXP daily close at 16:00 ET.
# Use 16:00 ET for cash close. For 0DTE PM-settled, official settlement is 16:00 ET for index value.
def expiration_close_utc(date: dt.date, underlying: str) -> dt.datetime:
    """Return the official 0DTE close time in UTC (assuming US Eastern DST May = UTC-4)."""
    # Hardcoded for May 2026 (DST). For production we'd use pytz/zoneinfo.
    # 16:00 ET = 20:00 UTC during DST.
    return dt.datetime.combine(date, dt.time(20, 0, 0), tzinfo=dt.UTC)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--underlying", required=True, choices=list(PARENT_SYMBOL.keys()))
    parser.add_argument("--date", required=True, help="YYYY-MM-DD trade date")
    parser.add_argument("--time", default="14:00", help="HH:MM ET snapshot time within RTH")
    parser.add_argument("--r", type=float, default=DEFAULT_R, help="Risk-free rate (continuous)")
    parser.add_argument("--q", type=float, default=None, help="Dividend yield (continuous, default per-underlying)")
    parser.add_argument("--n-major", type=int, default=3, help="N for major long/short GEX")
    parser.add_argument("--out-csv", default=None, help="Path to write per-strike CSV")
    parser.add_argument("--api-key", default=os.environ.get("DATABENTO_API_KEY"))
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: DATABENTO_API_KEY not set and --api-key not provided.", file=sys.stderr)
        return 2

    trade_date = dt.date.fromisoformat(args.date)
    target_expiration = trade_date  # 0DTE only
    hh, mm = (int(x) for x in args.time.split(":"))
    # ET to UTC (assume DST)
    snapshot_ts = dt.datetime.combine(trade_date, dt.time(hh + 4, mm), tzinfo=dt.UTC)

    underlying = args.underlying
    parent_symbol = PARENT_SYMBOL[underlying]
    q = args.q if args.q is not None else DEFAULT_Q.get(underlying, 0.013)
    r = args.r

    print("=== Snapshot CLI ===")
    print(f"Underlying        : {underlying}")
    print(f"Parent symbol     : {parent_symbol}")
    print(f"Trade date        : {trade_date}")
    print(f"Target expiration : {target_expiration} (0DTE)")
    print(f"Snapshot UTC      : {snapshot_ts.isoformat()}")
    print(f"r, q              : {r:.4f}, {q:.4f}")
    print()

    client = db.Historical(key=args.api_key)

    print("Loading definitions...", flush=True)
    defs = databento_loader.load_definitions(client, parent_symbol, trade_date, target_expiration)
    print(f"  {len(defs)} 0DTE instruments")
    if not defs:
        print("No 0DTE instruments found. Try a different date.", file=sys.stderr)
        return 3

    print("Loading open interest (statistics)...", flush=True)
    oi_map = databento_loader.load_open_interest(client, parent_symbol, trade_date)
    print(f"  {len(oi_map)} OI records")

    iids = [d.instrument_id for d in defs]
    print(f"Loading CBBO at {snapshot_ts} for {len(iids)} 0DTE instruments...", flush=True)
    quotes = databento_loader.load_cbbo_at(client, iids, snapshot_ts, window_seconds=120)
    print(f"  {len(quotes)} quote records")

    # Cumulative volume from session open (13:30 UTC = 9:30 ET) to snapshot
    session_open = dt.datetime.combine(trade_date, dt.time(13, 30), tzinfo=dt.UTC)
    print(f"Loading cumulative volume {session_open}-{snapshot_ts} for {len(iids)} instruments...", flush=True)
    vol_map = databento_loader.load_cumulative_volume(client, iids, session_open, snapshot_ts)
    print(f"  {len(vol_map)} volume records")

    print("Building chain snapshot & computing levels...", flush=True)
    chain = databento_loader.build_chain_snapshot(
        definitions=defs,
        oi_by_iid=oi_map,
        quotes_by_iid=quotes,
        volume_by_iid=vol_map,
        snapshot_ts=snapshot_ts,
        expiration_close_utc=expiration_close_utc(trade_date, underlying),
        r=r, q=q,
        underlying=underlying,
    )

    print()
    print("=== Chain summary ===")
    print(f"Strikes total        : {len(chain.strikes)}")
    print(f"Strike range         : [{chain.strikes.min():.0f}, {chain.strikes.max():.0f}]")
    print(f"T (years)            : {chain.T:.6f}  ({chain.T*365*24:.2f} hours)")
    print(f"Synthetic forward F  : {chain.forward:.4f}")
    print(f"Spot implied         : {chain.spot:.4f}")
    print(f"Valid IV calls       : {int(np.isfinite(chain.iv_call).sum())}")
    print(f"Valid IV puts        : {int(np.isfinite(chain.iv_put).sum())}")

    snap = compute.compute_levels(chain, n_major=args.n_major)

    print()
    print("=== Levels ===")
    print(f"Zero gamma           : {snap.zero_gamma.zero_gamma:.4f}")
    print(f"  bracket            : [{snap.zero_gamma.bracket_lo:.2f}, {snap.zero_gamma.bracket_hi:.2f}]")
    print(f"  in_bracket         : {snap.zero_gamma.in_bracket}")
    print(f"  fallback_used      : {snap.zero_gamma.fallback_used}")
    if snap.zero_gamma.note:
        print(f"  note               : {snap.zero_gamma.note}")
    if snap.call_wall:
        print(f"Call Wall            : {snap.call_wall.strike:.0f} (OI {snap.call_wall.oi:.0f})")
    if snap.put_wall:
        print(f"Put Wall             : {snap.put_wall.strike:.0f} (OI {snap.put_wall.oi:.0f})")

    print()
    print(f"Major long GEX (top {args.n_major} by VOLUME):")
    for lvl in snap.major_long_gex:
        print(f"  K={lvl.strike:.0f}   gex={lvl.gex:+.3e}")
    print(f"Major short GEX (top {args.n_major} by VOLUME):")
    for lvl in snap.major_short_gex:
        print(f"  K={lvl.strike:.0f}   gex={lvl.gex:+.3e}")

    print()
    print(f"Total GEX (volume): {snap.diagnostics['total_gex_volume']:+.3e}")
    print(f"Total GEX (OI)    : {snap.diagnostics['total_gex_oi']:+.3e}")

    # Per-strike CSV dump
    out_csv = args.out_csv or f"snapshot_{underlying}_{trade_date}_{args.time.replace(':', '')}.csv"
    df = pd.DataFrame({
        "strike": chain.strikes,
        "iv_call": chain.iv_call,
        "iv_put": chain.iv_put,
        "oi_call": chain.oi_call,
        "oi_put": chain.oi_put,
        "vol_call": chain.vol_call,
        "vol_put": chain.vol_put,
        "gex_oi": compute.gex_per_strike(chain, use_volume=False),
        "gex_volume": compute.gex_per_strike(chain, use_volume=True),
    })
    df.to_csv(out_csv, index=False)
    print(f"\nPer-strike CSV written: {out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
