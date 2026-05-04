"""Manual verification: pick one strike from the live snapshot and re-derive
GEX from raw inputs by hand to sanity-check the engine's output.

Usage:
    uv run python scripts/manual_verify.py --csv /tmp/snap_spxw_clean.csv --strike 7250 --F 7251.80 --T-hours 2.0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from optionflow import greeks  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--strike", type=float, required=True)
    p.add_argument("--F", type=float, required=True)
    p.add_argument("--T-hours", type=float, required=True)
    p.add_argument("--r", type=float, default=0.043)
    p.add_argument("--q", type=float, default=0.013)
    args = p.parse_args()

    df = pd.read_csv(args.csv)
    row = df[df["strike"] == args.strike]
    if row.empty:
        print(f"Strike {args.strike} not found in {args.csv}")
        return 2

    K = args.strike
    F = args.F
    T = args.T_hours / (365.0 * 24.0)
    sigma = float(row["iv_call"].iloc[0])  # iv_call == iv_put after unification
    oi_call = float(row["oi_call"].iloc[0])
    oi_put = float(row["oi_put"].iloc[0])
    vol_call = float(row["vol_call"].iloc[0])
    vol_put = float(row["vol_put"].iloc[0])
    gex_oi_engine = float(row["gex_oi"].iloc[0])
    gex_vol_engine = float(row["gex_volume"].iloc[0])

    print(f"=== Manual verification at K={K} ===")
    print(f"F (forward)      : {F}")
    print(f"K                : {K}")
    print(f"T (years)        : {T:.6e}  ({args.T_hours:.2f} hours)")
    print(f"sigma (IV)       : {sigma:.4f}")
    print(f"r, q             : {args.r}, {args.q}")
    print(f"OI call, put     : {oi_call:.0f}, {oi_put:.0f}")
    print(f"Vol call, put    : {vol_call:.0f}, {vol_put:.0f}")
    print()

    # Compute gamma at this strike, evaluated at S=F
    g = float(greeks.gamma(F, K, T, args.r, args.q, sigma))
    print(f"BSM gamma(F, K, T, r, q, sigma) = {g:.6e}")
    print()

    # GEX formula: gex(K) = (gamma * OI_call - gamma * OI_put) * 100 * F^2 * 0.01
    multiplier = 100.0 * F * F * 0.01
    gex_oi_manual = g * (oi_call - oi_put) * multiplier
    gex_vol_manual = g * (vol_call - vol_put) * multiplier

    print(f"Multiplier (100 * F^2 * 0.01) = {multiplier:.4f}")
    print()
    print("GEX-by-OI (manual)   = gamma * (OI_call - OI_put) * 100 * F^2 * 0.01")
    print(f"                     = {g:.4e} * ({oi_call:.0f} - {oi_put:.0f}) * {multiplier:.4f}")
    print(f"                     = {gex_oi_manual:+.4e}")
    print(f"GEX-by-OI (engine)   = {gex_oi_engine:+.4e}")
    print(f"  match              = {np.isclose(gex_oi_manual, gex_oi_engine)}")
    print()
    print("GEX-by-Volume (manual) = gamma * (vol_call - vol_put) * 100 * F^2 * 0.01")
    print(f"                       = {g:.4e} * ({vol_call:.0f} - {vol_put:.0f}) * {multiplier:.4f}")
    print(f"                       = {gex_vol_manual:+.4e}")
    print(f"GEX-by-Volume (engine) = {gex_vol_engine:+.4e}")
    print(f"  match                = {np.isclose(gex_vol_manual, gex_vol_engine)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
