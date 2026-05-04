"""Implied volatility solver for European index options.

Strategy:
1. Sanity-check market price is in arbitrage-free bounds.
2. Use Newton-Raphson with vega derivative (fast quadratic convergence).
3. Fall back to Brent's method on a bracket if Newton fails.

The solver is designed for batch use over an option chain. It runs per-element
because iterative solvers don't trivially vectorize, but each iteration is cheap.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from scipy.optimize import brentq

from . import greeks

OptionType = Literal["C", "P"]

_MIN_VOL = 1e-4
_MAX_VOL = 5.0  # 500% IV upper bound (more than enough for 0DTE)
_NR_MAX_ITER = 50
_NR_TOL = 1e-7


def _intrinsic(S: float, K: float, T: float, r: float, q: float, opt: OptionType) -> float:
    """Forward-discounted intrinsic = arbitrage-free lower bound on option price."""
    disc_r = np.exp(-r * T)
    disc_q = np.exp(-q * T)
    if opt == "C":
        return max(S * disc_q - K * disc_r, 0.0)
    return max(K * disc_r - S * disc_q, 0.0)


def _upper_bound(S: float, K: float, T: float, r: float, q: float, opt: OptionType) -> float:
    """Arbitrage-free upper bound on option price."""
    if opt == "C":
        return float(S * np.exp(-q * T))
    return float(K * np.exp(-r * T))


def implied_vol_one(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    opt: OptionType,
    initial_guess: float = 0.20,
) -> float:
    """Solve for sigma such that BSM price equals market_price.

    Returns NaN if input is outside arbitrage-free bounds or solver fails.
    """
    if not np.isfinite(market_price) or market_price <= 0:
        return float("nan")
    if T <= 0:
        return float("nan")

    lb = _intrinsic(S, K, T, r, q, opt)
    ub = _upper_bound(S, K, T, r, q, opt)
    # Allow a tiny epsilon below intrinsic (rounding noise)
    if market_price < lb - 1e-6 or market_price > ub + 1e-6:
        return float("nan")
    # Clamp very close to bounds
    market_price = float(np.clip(market_price, lb + 1e-9, ub - 1e-9))

    # ---------- Newton-Raphson ----------
    sigma = max(initial_guess, _MIN_VOL)
    for _ in range(_NR_MAX_ITER):
        p = float(greeks.price(S, K, T, r, q, sigma, opt))
        diff = p - market_price
        if abs(diff) < _NR_TOL:
            return float(np.clip(sigma, _MIN_VOL, _MAX_VOL))
        v = float(greeks.vega(S, K, T, r, q, sigma))
        if v < 1e-10:
            break  # vega collapsed, switch to Brent
        sigma -= diff / v
        if sigma <= _MIN_VOL or sigma >= _MAX_VOL or not np.isfinite(sigma):
            break

    # ---------- Brent fallback ----------
    def f(s: float) -> float:
        return float(greeks.price(S, K, T, r, q, s, opt) - market_price)

    try:
        f_lo = f(_MIN_VOL)
        f_hi = f(_MAX_VOL)
        if f_lo * f_hi > 0:
            # No bracket: market price unattainable in [_MIN_VOL, _MAX_VOL]
            return float("nan")
        return float(brentq(f, _MIN_VOL, _MAX_VOL, xtol=1e-7, maxiter=200))
    except Exception:
        return float("nan")


def implied_vol_batch(
    market_prices: np.ndarray,
    S: float,
    Ks: np.ndarray,
    T: float,
    r: float,
    q: float,
    opt: OptionType,
) -> np.ndarray:
    """Vectorized convenience wrapper. Runs per-element."""
    n = len(market_prices)
    out = np.empty(n, dtype=float)
    for i in range(n):
        out[i] = implied_vol_one(
            market_price=float(market_prices[i]),
            S=S,
            K=float(Ks[i]),
            T=T,
            r=r,
            q=q,
            opt=opt,
        )
    return out


def mid_price(bid: float, ask: float, max_spread_pct: float = 0.50) -> float:
    """Compute mid quote with spread sanity filter.

    Returns NaN if bid <= 0, ask <= 0, or spread > max_spread_pct of mid.
    """
    if not (np.isfinite(bid) and np.isfinite(ask)):
        return float("nan")
    if bid <= 0 or ask <= 0 or ask <= bid:
        return float("nan")
    mid = 0.5 * (bid + ask)
    spread = ask - bid
    if mid > 0 and spread / mid > max_spread_pct:
        return float("nan")
    return float(mid)
