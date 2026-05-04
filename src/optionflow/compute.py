"""GEX, Zero Gamma, and Put/Call Wall computations from a 0DTE option chain.

Convention used (matches SpotGamma / GEXBOT public documentation):
    GEX_per_strike(K) = (gamma_C(K) * Q_C(K) - gamma_P(K) * Q_P(K)) * 100 * S^2 * 0.01

where Q is either Open Interest (OI) or Volume. The 100 factor is the contract
multiplier; the S^2 * 0.01 converts gamma into dollar exposure per 1% spot move.

Sign convention:
    positive GEX(K) -> dealers buy dips / sell rallies near K (stabilizing)
    negative GEX(K) -> dealers sell dips / buy rallies near K (destabilizing)

Zero Gamma is the spot level S* at which the *aggregated* dealer gamma flips
sign. Computed by root-finding on Brent's method, constrained to lie between
the most-negative GEX strike (below current F) and the most-positive GEX strike
(above current F), as measured by volume.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

from . import greeks

# ---------------------------------------------------------------------------
# Input data structure
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChainSnapshot:
    """All per-strike inputs needed for GEX / ZG / Wall computation.

    Arrays must be 1D with same length, sorted by strike ascending.
    Fields with no quote at a given strike should be NaN (will be filtered).
    """

    strikes: np.ndarray  # shape (n,)
    iv_call: np.ndarray  # shape (n,) implied vol per call strike
    iv_put: np.ndarray  # shape (n,) implied vol per put strike
    oi_call: np.ndarray  # shape (n,)
    oi_put: np.ndarray  # shape (n,)
    vol_call: np.ndarray  # shape (n,) cumulative volume call
    vol_put: np.ndarray  # shape (n,) cumulative volume put

    forward: float  # estimated synthetic forward F
    spot: float  # spot implied (or use F directly)
    T: float  # time to expiry in years
    r: float  # risk-free rate
    q: float  # dividend yield
    underlying: str  # e.g. "SPXW"
    expiration: str  # ISO date "2026-05-03"

    def __post_init__(self) -> None:
        n = len(self.strikes)
        for name in ("iv_call", "iv_put", "oi_call", "oi_put", "vol_call", "vol_put"):
            arr = getattr(self, name)
            if len(arr) != n:
                raise ValueError(f"{name} length {len(arr)} != strikes length {n}")
        if not np.all(np.diff(self.strikes) > 0):
            raise ValueError("strikes must be strictly increasing")
        if self.T <= 0:
            raise ValueError("T must be positive")


# ---------------------------------------------------------------------------
# Per-strike GEX
# ---------------------------------------------------------------------------


def gex_per_strike(
    chain: ChainSnapshot,
    *,
    spot: float | None = None,
    use_volume: bool = False,
) -> np.ndarray:
    """Compute GEX at each strike.

    Args:
        chain: ChainSnapshot
        spot: hypothetical spot level (defaults to chain.forward). Used by
              zero-gamma search to evaluate GEX at non-current spots.
        use_volume: True for GEX-by-Volume, False for GEX-by-OI.

    Returns:
        gex array, same length as chain.strikes. NaN-safe (zero-fills missing).
    """
    S = float(spot if spot is not None else chain.forward)
    K = chain.strikes
    T, r, q = chain.T, chain.r, chain.q

    # gamma per strike (call/put gamma identical given same sigma)
    # We use *separate* IV per side because OPRA quotes have side-specific smile noise.
    sigma_c = np.where(np.isfinite(chain.iv_call), chain.iv_call, 0.0)
    sigma_p = np.where(np.isfinite(chain.iv_put), chain.iv_put, 0.0)

    g_c = greeks.gamma(S, K, T, r, q, sigma_c)
    g_p = greeks.gamma(S, K, T, r, q, sigma_p)

    if use_volume:
        Q_c = np.where(np.isfinite(chain.vol_call), chain.vol_call, 0.0)
        Q_p = np.where(np.isfinite(chain.vol_put), chain.vol_put, 0.0)
    else:
        Q_c = np.where(np.isfinite(chain.oi_call), chain.oi_call, 0.0)
        Q_p = np.where(np.isfinite(chain.oi_put), chain.oi_put, 0.0)

    multiplier = 100.0 * S * S * 0.01
    return (g_c * Q_c - g_p * Q_p) * multiplier


def net_gamma_at(chain: ChainSnapshot, S_prime: float, *, use_volume: bool = True) -> float:
    """Net gamma profile evaluated at hypothetical spot S'. Used for ZG root-find.

    Note: the multiplier (100 * S'^2 * 0.01) is positive, so we only need the sign
    of the gamma-weighted sum for root-finding. We return the full GEX-equivalent
    quantity for monotonicity diagnostics.
    """
    return float(np.sum(gex_per_strike(chain, spot=S_prime, use_volume=use_volume)))


# ---------------------------------------------------------------------------
# Major long / short GEX strikes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GEXLevel:
    """A single GEX level (one strike)."""

    strike: float
    gex: float  # signed; positive = long gamma, negative = short gamma
    by: str  # "volume" or "oi"


def major_long_short_gex(
    chain: ChainSnapshot,
    *,
    n: int = 3,
    use_volume: bool = True,
) -> tuple[list[GEXLevel], list[GEXLevel]]:
    """Return (top N positive strikes, top N most-negative strikes) by GEX magnitude.

    Args:
        chain: ChainSnapshot
        n: number of strikes per side (1..5 typical)
        use_volume: True for GEX-by-Volume (default per spec), False for OI

    Returns:
        (major_long, major_short) — each is a list sorted by absolute |gex| desc.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    g = gex_per_strike(chain, use_volume=use_volume)
    by_label = "volume" if use_volume else "oi"

    pos_idx = np.where(g > 0)[0]
    neg_idx = np.where(g < 0)[0]

    # sort positive descending by gex value
    pos_sorted = pos_idx[np.argsort(-g[pos_idx])]
    # sort negative ascending by gex value (most negative first)
    neg_sorted = neg_idx[np.argsort(g[neg_idx])]

    major_long = [
        GEXLevel(strike=float(chain.strikes[i]), gex=float(g[i]), by=by_label)
        for i in pos_sorted[:n]
    ]
    major_short = [
        GEXLevel(strike=float(chain.strikes[i]), gex=float(g[i]), by=by_label)
        for i in neg_sorted[:n]
    ]
    return major_long, major_short


# ---------------------------------------------------------------------------
# Zero Gamma with constraint
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ZeroGammaResult:
    """Result of zero-gamma search."""

    zero_gamma: float  # spot level at which net gamma = 0 (NaN if not found)
    bracket_lo: float  # lower bound used in search (typically major short strike)
    bracket_hi: float  # upper bound (typically major long strike)
    in_bracket: bool  # whether root was found within the constrained bracket
    fallback_used: bool  # whether widened bracket was needed
    note: str = ""


def zero_gamma(
    chain: ChainSnapshot,
    *,
    n_for_constraint: int = 3,
    widen_pct: float = 0.10,
) -> ZeroGammaResult:
    """Find S* where net gamma = 0, constrained between major-volume short & long strikes.

    Strategy:
        1. Compute major short / long GEX strikes by VOLUME using top-N (default 3).
        2. Pick the lowest major-short strike below F (or just lowest major-short)
           and highest major-long strike above F (or just highest major-long).
        3. If sign change in net_gamma exists in that bracket -> Brent root.
        4. Otherwise widen bracket by widen_pct on each side and retry.
        5. As last resort, scan whole strike range; report fallback_used=True.
    """
    F = chain.forward
    long_levels, short_levels = major_long_short_gex(chain, n=n_for_constraint, use_volume=True)

    if not long_levels or not short_levels:
        return ZeroGammaResult(
            zero_gamma=float("nan"),
            bracket_lo=float("nan"),
            bracket_hi=float("nan"),
            in_bracket=False,
            fallback_used=True,
            note="no positive or negative GEX strikes by volume",
        )

    # Bracket: lowest major-short strike to highest major-long strike
    # (we don't strictly require below/above F since for 0DTE positioning may flip)
    short_strikes = sorted(s.strike for s in short_levels)
    long_strikes = sorted(s.strike for s in long_levels)

    # Try the natural ordering: lowest short below F, highest long above F
    shorts_below = [s for s in short_strikes if s < F]
    longs_above = [s for s in long_strikes if s > F]
    if shorts_below and longs_above:
        lo = max(shorts_below)  # nearest short below F
        hi = min(longs_above)  # nearest long above F
    else:
        # Fallback: use full short/long range
        lo = min(short_strikes)
        hi = max(long_strikes)
    if lo >= hi:
        # swap if needed
        lo, hi = min(lo, hi), max(lo, hi)
        if lo == hi:
            hi = lo * 1.001

    def f(S_prime: float) -> float:
        return net_gamma_at(chain, S_prime, use_volume=True)

    # Sample to detect sign change in primary bracket
    f_lo = f(lo)
    f_hi = f(hi)
    note = ""

    if not np.isfinite(f_lo) or not np.isfinite(f_hi):
        return ZeroGammaResult(
            zero_gamma=float("nan"),
            bracket_lo=lo,
            bracket_hi=hi,
            in_bracket=False,
            fallback_used=True,
            note="non-finite net gamma at bracket bounds",
        )

    if f_lo * f_hi < 0:
        try:
            zg = brentq(f, lo, hi, xtol=1e-3, maxiter=100)
            return ZeroGammaResult(
                zero_gamma=float(zg),
                bracket_lo=lo,
                bracket_hi=hi,
                in_bracket=True,
                fallback_used=False,
            )
        except Exception as e:
            note = f"Brent failed in primary bracket: {e}"

    # Widen bracket
    lo_w = lo * (1.0 - widen_pct)
    hi_w = hi * (1.0 + widen_pct)
    f_lo_w = f(lo_w)
    f_hi_w = f(hi_w)
    if f_lo_w * f_hi_w < 0:
        try:
            zg = brentq(f, lo_w, hi_w, xtol=1e-3, maxiter=100)
            return ZeroGammaResult(
                zero_gamma=float(zg),
                bracket_lo=lo,
                bracket_hi=hi,
                in_bracket=False,
                fallback_used=True,
                note=note or "root found only after widening bracket",
            )
        except Exception as e:
            note = f"{note} | wide-bracket Brent failed: {e}"

    # Last resort: scan whole strike range
    K_lo, K_hi = float(chain.strikes.min()), float(chain.strikes.max())
    f_K_lo = f(K_lo)
    f_K_hi = f(K_hi)
    if f_K_lo * f_K_hi < 0:
        try:
            zg = brentq(f, K_lo, K_hi, xtol=1e-3, maxiter=200)
            return ZeroGammaResult(
                zero_gamma=float(zg),
                bracket_lo=lo,
                bracket_hi=hi,
                in_bracket=False,
                fallback_used=True,
                note=(note or "") + " | root in full strike range only",
            )
        except Exception as e:
            note = f"{note} | full-range Brent failed: {e}"

    return ZeroGammaResult(
        zero_gamma=float("nan"),
        bracket_lo=lo,
        bracket_hi=hi,
        in_bracket=False,
        fallback_used=True,
        note=(note or "no sign change in any bracket"),
    )


# ---------------------------------------------------------------------------
# Put / Call Walls
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WallLevel:
    """Put/Call Wall result."""

    strike: float
    oi: float


def put_call_walls(chain: ChainSnapshot) -> tuple[WallLevel | None, WallLevel | None]:
    """Find Call Wall (max call OI strictly above F) and Put Wall (max put OI strictly below F).

    Returns:
        (call_wall, put_wall). Each may be None if no valid strike on that side.
    """
    F = chain.forward
    above = chain.strikes > F
    below = chain.strikes < F

    cw: WallLevel | None = None
    pw: WallLevel | None = None

    if above.any():
        oi_c_above = np.where(above, np.where(np.isfinite(chain.oi_call), chain.oi_call, 0.0), 0.0)
        if oi_c_above.max() > 0:
            i = int(np.argmax(oi_c_above))
            cw = WallLevel(strike=float(chain.strikes[i]), oi=float(oi_c_above[i]))

    if below.any():
        oi_p_below = np.where(below, np.where(np.isfinite(chain.oi_put), chain.oi_put, 0.0), 0.0)
        if oi_p_below.max() > 0:
            i = int(np.argmax(oi_p_below))
            pw = WallLevel(strike=float(chain.strikes[i]), oi=float(oi_p_below[i]))

    return cw, pw


# ---------------------------------------------------------------------------
# Top-level snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LevelsSnapshot:
    """Final outputs to publish to indicators."""

    underlying: str
    expiration: str
    forward: float
    spot_implied: float
    zero_gamma: ZeroGammaResult
    call_wall: WallLevel | None
    put_wall: WallLevel | None
    major_long_gex: list[GEXLevel] = field(default_factory=list)
    major_short_gex: list[GEXLevel] = field(default_factory=list)
    n_strikes_total: int = 0
    diagnostics: dict[str, float] = field(default_factory=dict)


def compute_levels(chain: ChainSnapshot, *, n_major: int = 3) -> LevelsSnapshot:
    """Run the full computation: GEX, walls, ZG."""
    long_levels, short_levels = major_long_short_gex(chain, n=n_major, use_volume=True)
    zg = zero_gamma(chain, n_for_constraint=n_major)
    cw, pw = put_call_walls(chain)

    diagnostics = {
        "total_gex_volume": float(np.sum(gex_per_strike(chain, use_volume=True))),
        "total_gex_oi": float(np.sum(gex_per_strike(chain, use_volume=False))),
        "n_valid_iv_calls": int(np.isfinite(chain.iv_call).sum()),
        "n_valid_iv_puts": int(np.isfinite(chain.iv_put).sum()),
    }

    return LevelsSnapshot(
        underlying=chain.underlying,
        expiration=chain.expiration,
        forward=chain.forward,
        spot_implied=chain.spot,
        zero_gamma=zg,
        call_wall=cw,
        put_wall=pw,
        major_long_gex=long_levels,
        major_short_gex=short_levels,
        n_strikes_total=len(chain.strikes),
        diagnostics=diagnostics,
    )
