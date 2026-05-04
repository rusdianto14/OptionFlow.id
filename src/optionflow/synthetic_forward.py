"""Synthetic forward estimation via put-call parity.

For European options on an index with continuous dividend yield q:
    C(K) - P(K) = S * exp(-qT) - K * exp(-rT)

Multiplying by exp(rT):
    (C - P) * exp(rT) = S * exp((r-q)T) - K = F - K

Therefore: F = (C - P) * exp(rT) + K.

In a perfect market F_K should be constant across strikes. In practice quote
noise (especially deep ITM/OTM) makes outer strikes unreliable. We compute F
robustly by:
1. Estimating a rough median F across all valid call-put pairs.
2. Selecting the N strikes closest to the rough estimate (most-ATM).
3. Returning their (weighted) mean.

Reference: Hull, "Options, Futures, and Other Derivatives", Ch.5 (Forward & Futures
prices) and Ch.11 (Properties of stock options).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class ForwardEstimate:
    """Result of synthetic-forward fit."""

    forward: float  # estimated F
    spot_implied: float  # F * exp(-(r-q)T)
    n_strikes_used: int  # how many strikes contributed
    k_min: float  # strike range used (low)
    k_max: float  # strike range used (high)
    raw_estimates: np.ndarray  # F_K for all valid pairs (for debugging)


def estimate_forward(
    strikes: np.ndarray,
    call_mids: np.ndarray,
    put_mids: np.ndarray,
    T: float,
    r: float,
    q: float,
    n_atm: int = 10,
) -> ForwardEstimate:
    """Estimate forward price F from call-put pairs across strikes.

    Args:
        strikes: array of strikes K
        call_mids: array of call mid prices (same shape as strikes); NaN where invalid
        put_mids: array of put mid prices (same shape as strikes); NaN where invalid
        T: time to expiry in years
        r: risk-free rate (continuous)
        q: dividend yield (continuous)
        n_atm: number of most-ATM valid strikes to use in final mean

    Returns:
        ForwardEstimate. If too few valid pairs, returns NaN forward.
    """
    if T <= 0:
        raise ValueError("T must be positive for forward estimation")
    K = np.asarray(strikes, dtype=float)
    C = np.asarray(call_mids, dtype=float)
    P = np.asarray(put_mids, dtype=float)
    if not (K.shape == C.shape == P.shape):
        raise ValueError("strikes, call_mids, put_mids must have same shape")

    valid = np.isfinite(C) & np.isfinite(P) & (C > 0) & (P > 0)
    if valid.sum() < 3:
        return ForwardEstimate(
            forward=float("nan"),
            spot_implied=float("nan"),
            n_strikes_used=0,
            k_min=float("nan"),
            k_max=float("nan"),
            raw_estimates=np.array([]),
        )

    K_v = K[valid]
    C_v = C[valid]
    P_v = P[valid]

    # F_K candidates from each valid pair
    erT = np.exp(r * T)
    F_candidates = (C_v - P_v) * erT + K_v

    # Rough median anchor (robust to outliers)
    rough_F = float(np.median(F_candidates))

    # Pick top-N strikes closest to rough_F (most ATM)
    distances = np.abs(K_v - rough_F)
    n_select = min(n_atm, len(K_v))
    idx_sorted = np.argsort(distances)[:n_select]
    selected_F = F_candidates[idx_sorted]
    selected_K = K_v[idx_sorted]

    # Weighted mean by 1/(distance+small) to bias toward most-ATM
    weights = 1.0 / (distances[idx_sorted] + 1.0)
    F_final = float(np.average(selected_F, weights=weights))

    spot = F_final * np.exp(-(r - q) * T)

    return ForwardEstimate(
        forward=F_final,
        spot_implied=spot,
        n_strikes_used=int(n_select),
        k_min=float(selected_K.min()),
        k_max=float(selected_K.max()),
        raw_estimates=F_candidates,
    )
