"""Generalized Black-Scholes-Merton Greeks for European index options.

Reference: Haug (2007), "The Complete Guide to Option Pricing Formulas".

For an index with continuous dividend yield q and risk-free rate r,
the BSM diffusion is dS = (r - q) S dt + sigma S dW (under risk-neutral measure).

This module provides vectorized Greeks suitable for computing GEX on a full chain.
All inputs may be scalars or 1D numpy arrays (broadcast against each other).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.stats import norm

OptionType = Literal["C", "P"]

_SQRT_EPS = 1e-12


def _validate_inputs(
    S: float | np.ndarray,
    K: float | np.ndarray,
    T: float | np.ndarray,
    sigma: float | np.ndarray,
) -> None:
    """Lightweight sanity check; numpy will broadcast on use."""
    arr_T = np.asarray(T, dtype=float)
    arr_sigma = np.asarray(sigma, dtype=float)
    if np.any(arr_T < 0):
        raise ValueError("Time to expiry T must be non-negative")
    if np.any(arr_sigma < 0):
        raise ValueError("Volatility sigma must be non-negative")
    arr_S = np.asarray(S, dtype=float)
    arr_K = np.asarray(K, dtype=float)
    if np.any(arr_S <= 0) or np.any(arr_K <= 0):
        raise ValueError("Spot S and strike K must be positive")


def d1_d2(
    S: float | np.ndarray,
    K: float | np.ndarray,
    T: float | np.ndarray,
    r: float,
    q: float,
    sigma: float | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute d1 and d2 of generalized BSM. Vectorized."""
    S_a = np.asarray(S, dtype=float)
    K_a = np.asarray(K, dtype=float)
    T_a = np.asarray(T, dtype=float)
    sigma_a = np.asarray(sigma, dtype=float)

    sqrtT = np.sqrt(np.maximum(T_a, _SQRT_EPS))
    sigma_sqrtT = sigma_a * sqrtT
    # avoid division-by-zero; for sigma_sqrtT==0 d1 is ill-defined -> we'll mask later
    sigma_sqrtT_safe = np.where(sigma_sqrtT > 0, sigma_sqrtT, np.nan)
    d1 = (np.log(S_a / K_a) + (r - q + 0.5 * sigma_a**2) * T_a) / sigma_sqrtT_safe
    d2 = d1 - sigma_sqrtT
    return d1, d2


def price(
    S: float | np.ndarray,
    K: float | np.ndarray,
    T: float | np.ndarray,
    r: float,
    q: float,
    sigma: float | np.ndarray,
    option_type: OptionType,
) -> np.ndarray:
    """Black-Scholes-Merton European option price for index (continuous q)."""
    _validate_inputs(S, K, T, sigma)
    S_a = np.asarray(S, dtype=float)
    K_a = np.asarray(K, dtype=float)
    T_a = np.asarray(T, dtype=float)
    sigma_a = np.asarray(sigma, dtype=float)

    # Boundary at expiry: payoff intrinsic
    expired = T_a <= 0
    zero_vol = sigma_a <= 0

    d1, d2 = d1_d2(S_a, K_a, T_a, r, q, sigma_a)
    disc_r = np.exp(-r * T_a)
    disc_q = np.exp(-q * T_a)

    if option_type == "C":
        bsm = S_a * disc_q * norm.cdf(d1) - K_a * disc_r * norm.cdf(d2)
        intrinsic = np.maximum(S_a - K_a, 0.0)
        forward_intrinsic = np.maximum(S_a * disc_q - K_a * disc_r, 0.0)
    elif option_type == "P":
        bsm = K_a * disc_r * norm.cdf(-d2) - S_a * disc_q * norm.cdf(-d1)
        intrinsic = np.maximum(K_a - S_a, 0.0)
        forward_intrinsic = np.maximum(K_a * disc_r - S_a * disc_q, 0.0)
    else:
        raise ValueError(f"option_type must be 'C' or 'P', got {option_type!r}")

    out = np.where(expired, intrinsic, bsm)
    out = np.where(zero_vol & ~expired, forward_intrinsic, out)
    return out


def delta(
    S: float | np.ndarray,
    K: float | np.ndarray,
    T: float | np.ndarray,
    r: float,
    q: float,
    sigma: float | np.ndarray,
    option_type: OptionType,
) -> np.ndarray:
    """Delta = dPrice/dS. For call >=0, for put <=0."""
    _validate_inputs(S, K, T, sigma)
    T_a = np.asarray(T, dtype=float)
    sigma_a = np.asarray(sigma, dtype=float)
    S_a = np.asarray(S, dtype=float)
    K_a = np.asarray(K, dtype=float)

    d1, _ = d1_d2(S_a, K_a, T_a, r, q, sigma_a)
    disc_q = np.exp(-q * T_a)

    expired_call = (T_a <= 0) & (option_type == "C")
    expired_put = (T_a <= 0) & (option_type == "P")

    if option_type == "C":
        out = disc_q * norm.cdf(d1)
        # at expiry: delta = 1 if ITM else 0
        out = np.where(expired_call, np.where(S_a > K_a, 1.0, 0.0), out)
    elif option_type == "P":
        out = -disc_q * norm.cdf(-d1)
        out = np.where(expired_put, np.where(S_a < K_a, -1.0, 0.0), out)
    else:
        raise ValueError(f"option_type must be 'C' or 'P', got {option_type!r}")

    # zero-vol: deterministic forward case
    zero_vol = sigma_a <= 0
    if option_type == "C":
        zv = np.where(S_a * disc_q > K_a * np.exp(-r * T_a), disc_q, 0.0)
    else:
        zv = np.where(S_a * disc_q < K_a * np.exp(-r * T_a), -disc_q, 0.0)
    out = np.where(zero_vol & (T_a > 0), zv, out)
    return out


def gamma(
    S: float | np.ndarray,
    K: float | np.ndarray,
    T: float | np.ndarray,
    r: float,
    q: float,
    sigma: float | np.ndarray,
) -> np.ndarray:
    """Gamma = d2 Price / dS2. Same for call and put."""
    _validate_inputs(S, K, T, sigma)
    T_a = np.asarray(T, dtype=float)
    sigma_a = np.asarray(sigma, dtype=float)
    S_a = np.asarray(S, dtype=float)
    K_a = np.asarray(K, dtype=float)

    d1, _ = d1_d2(S_a, K_a, T_a, r, q, sigma_a)
    disc_q = np.exp(-q * T_a)
    sqrtT = np.sqrt(np.maximum(T_a, _SQRT_EPS))
    sigma_S_sqrtT = sigma_a * S_a * sqrtT

    # avoid div-by-zero where vol*sqrt(T) collapses; mark NaN then set to 0
    safe_denom = np.where(sigma_S_sqrtT > 0, sigma_S_sqrtT, np.nan)
    out = disc_q * norm.pdf(d1) / safe_denom
    out = np.where(np.isfinite(out), out, 0.0)
    # at expiry gamma is 0 except infinitely peaked at K (ignore)
    out = np.where(T_a <= 0, 0.0, out)
    out = np.where(sigma_a <= 0, 0.0, out)
    return out


def vega(
    S: float | np.ndarray,
    K: float | np.ndarray,
    T: float | np.ndarray,
    r: float,
    q: float,
    sigma: float | np.ndarray,
) -> np.ndarray:
    """Vega = dPrice/dsigma. Same for call and put. Per 1.00 vol (not per 1%)."""
    _validate_inputs(S, K, T, sigma)
    T_a = np.asarray(T, dtype=float)
    sigma_a = np.asarray(sigma, dtype=float)
    S_a = np.asarray(S, dtype=float)
    K_a = np.asarray(K, dtype=float)

    d1, _ = d1_d2(S_a, K_a, T_a, r, q, sigma_a)
    disc_q = np.exp(-q * T_a)
    sqrtT = np.sqrt(np.maximum(T_a, _SQRT_EPS))
    out = S_a * disc_q * norm.pdf(d1) * sqrtT
    out = np.where(T_a <= 0, 0.0, out)
    out = np.where(sigma_a <= 0, 0.0, out)
    return out


def theta(
    S: float | np.ndarray,
    K: float | np.ndarray,
    T: float | np.ndarray,
    r: float,
    q: float,
    sigma: float | np.ndarray,
    option_type: OptionType,
) -> np.ndarray:
    """Theta = dPrice/dt (per year). For per-day theta, divide by 365 (or 252)."""
    _validate_inputs(S, K, T, sigma)
    T_a = np.asarray(T, dtype=float)
    sigma_a = np.asarray(sigma, dtype=float)
    S_a = np.asarray(S, dtype=float)
    K_a = np.asarray(K, dtype=float)

    d1, d2 = d1_d2(S_a, K_a, T_a, r, q, sigma_a)
    disc_r = np.exp(-r * T_a)
    disc_q = np.exp(-q * T_a)
    sqrtT = np.sqrt(np.maximum(T_a, _SQRT_EPS))

    decay = -S_a * disc_q * norm.pdf(d1) * sigma_a / (2.0 * sqrtT)
    if option_type == "C":
        out = decay - r * K_a * disc_r * norm.cdf(d2) + q * S_a * disc_q * norm.cdf(d1)
    elif option_type == "P":
        out = decay + r * K_a * disc_r * norm.cdf(-d2) - q * S_a * disc_q * norm.cdf(-d1)
    else:
        raise ValueError(f"option_type must be 'C' or 'P', got {option_type!r}")
    out = np.where(T_a <= 0, 0.0, out)
    return out


@dataclass(frozen=True, slots=True)
class GreeksBundle:
    """Container holding all Greeks for one option (or vector)."""

    delta: np.ndarray
    gamma: np.ndarray
    vega: np.ndarray
    theta: np.ndarray


def all_greeks(
    S: float | np.ndarray,
    K: float | np.ndarray,
    T: float | np.ndarray,
    r: float,
    q: float,
    sigma: float | np.ndarray,
    option_type: OptionType,
) -> GreeksBundle:
    """Compute delta, gamma, vega, theta in one shot (efficient for vectorized compute)."""
    return GreeksBundle(
        delta=delta(S, K, T, r, q, sigma, option_type),
        gamma=gamma(S, K, T, r, q, sigma),
        vega=vega(S, K, T, r, q, sigma),
        theta=theta(S, K, T, r, q, sigma, option_type),
    )
