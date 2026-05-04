"""Test GEX / Zero Gamma / Put-Call Wall on synthetic chains."""

from __future__ import annotations

import numpy as np
import pytest

from optionflow import compute

# ---------------------------------------------------------------------------
# Helpers: build a synthetic ChainSnapshot
# ---------------------------------------------------------------------------


def _make_chain(
    F: float = 5500.0,
    T_hours: float = 4.0,
    strike_low: float = 5400.0,
    strike_high: float = 5600.0,
    strike_step: float = 5.0,
    sigma_atm: float = 0.15,
    *,
    oi_call_pattern: np.ndarray | None = None,
    oi_put_pattern: np.ndarray | None = None,
    vol_call_pattern: np.ndarray | None = None,
    vol_put_pattern: np.ndarray | None = None,
    underlying: str = "SPXW",
) -> compute.ChainSnapshot:
    T = T_hours / (365.0 * 24.0)
    r, q = 0.043, 0.013
    strikes = np.arange(strike_low, strike_high + 0.5 * strike_step, strike_step, dtype=float)
    n = len(strikes)
    sigma = np.full(n, sigma_atm)

    # Default OI: peak at ATM, decline outward
    if oi_call_pattern is None:
        oi_call_pattern = 1000.0 * np.exp(-((strikes - F) / 50.0) ** 2)
    if oi_put_pattern is None:
        oi_put_pattern = 1000.0 * np.exp(-((strikes - F) / 50.0) ** 2)
    if vol_call_pattern is None:
        vol_call_pattern = 500.0 * np.exp(-((strikes - F) / 30.0) ** 2)
    if vol_put_pattern is None:
        vol_put_pattern = 500.0 * np.exp(-((strikes - F) / 30.0) ** 2)

    return compute.ChainSnapshot(
        strikes=strikes,
        iv_call=sigma,
        iv_put=sigma,
        oi_call=oi_call_pattern,
        oi_put=oi_put_pattern,
        vol_call=vol_call_pattern,
        vol_put=vol_put_pattern,
        forward=F,
        spot=F * np.exp(-(r - q) * T),
        T=T,
        r=r,
        q=q,
        underlying=underlying,
        expiration="2026-05-03",
    )


# ---------------------------------------------------------------------------
# Per-strike GEX
# ---------------------------------------------------------------------------


def test_gex_per_strike_zero_when_oi_balanced_and_strike_far():
    chain = _make_chain(oi_call_pattern=np.array([0.0]*41), oi_put_pattern=np.array([0.0]*41))
    g = compute.gex_per_strike(chain, use_volume=False)
    assert np.allclose(g, 0.0)


def test_gex_atm_dominates():
    """For symmetric OI, GEX should peak in magnitude near ATM strikes (gamma is highest there)."""
    chain = _make_chain()
    atm_idx = int(np.argmin(np.abs(chain.strikes - chain.forward)))
    # Asymmetric: more call OI than put OI -> positive GEX dominated by ATM gamma
    oi_c = 2000.0 * np.exp(-((chain.strikes - chain.forward) / 50.0) ** 2)
    oi_p = 1000.0 * np.exp(-((chain.strikes - chain.forward) / 50.0) ** 2)
    chain2 = compute.ChainSnapshot(
        strikes=chain.strikes, iv_call=chain.iv_call, iv_put=chain.iv_put,
        oi_call=oi_c, oi_put=oi_p, vol_call=chain.vol_call, vol_put=chain.vol_put,
        forward=chain.forward, spot=chain.spot, T=chain.T, r=chain.r, q=chain.q,
        underlying=chain.underlying, expiration=chain.expiration,
    )
    g2 = compute.gex_per_strike(chain2, use_volume=False)
    assert g2[atm_idx] > 0  # net call dominance, positive GEX
    # peak should be in middle (where gamma * OI is largest)
    peak_idx = int(np.argmax(g2))
    assert abs(peak_idx - atm_idx) <= 5


def test_gex_sign_flips_with_call_put_dominance():
    """Call OI > Put OI -> positive GEX; Put OI > Call OI -> negative."""
    n = 41
    strikes = np.arange(5400, 5605, 5.0)
    sigma = np.full(n, 0.15)
    oi_high = 1000.0 * np.exp(-((strikes - 5500) / 50.0) ** 2)
    oi_low = 200.0 * np.exp(-((strikes - 5500) / 50.0) ** 2)
    base = dict(strikes=strikes, iv_call=sigma, iv_put=sigma, vol_call=oi_high, vol_put=oi_low,
                forward=5500.0, spot=5500.0, T=4.0/(365*24), r=0.043, q=0.013,
                underlying="SPXW", expiration="2026-05-03")
    chain_call_dom = compute.ChainSnapshot(oi_call=oi_high, oi_put=oi_low, **base)
    chain_put_dom = compute.ChainSnapshot(oi_call=oi_low, oi_put=oi_high, **base)
    g_call = np.sum(compute.gex_per_strike(chain_call_dom, use_volume=False))
    g_put = np.sum(compute.gex_per_strike(chain_put_dom, use_volume=False))
    assert g_call > 0
    assert g_put < 0


# ---------------------------------------------------------------------------
# Major long/short GEX
# ---------------------------------------------------------------------------


def test_major_long_short_returns_n_levels():
    n = 41
    strikes = np.arange(5400, 5605, 5.0)
    sigma = np.full(n, 0.15)
    # Call-heavy above F, Put-heavy below F
    oi_call = np.where(strikes > 5500, 2000.0, 100.0)
    oi_put = np.where(strikes < 5500, 2000.0, 100.0)
    chain = compute.ChainSnapshot(
        strikes=strikes, iv_call=sigma, iv_put=sigma,
        oi_call=oi_call, oi_put=oi_put, vol_call=oi_call, vol_put=oi_put,
        forward=5500.0, spot=5500.0, T=4.0/(365*24), r=0.043, q=0.013,
        underlying="SPXW", expiration="2026-05-03",
    )
    longs, shorts = compute.major_long_short_gex(chain, n=3, use_volume=True)
    assert len(longs) == 3
    assert len(shorts) == 3
    # All longs should be ABOVE F (call-heavy zone), all shorts BELOW F (put-heavy)
    for lvl in longs:
        assert lvl.strike > 5500.0
        assert lvl.gex > 0
    for lvl in shorts:
        assert lvl.strike < 5500.0
        assert lvl.gex < 0
    # sorted by descending magnitude
    assert longs[0].gex >= longs[1].gex >= longs[2].gex
    assert shorts[0].gex <= shorts[1].gex <= shorts[2].gex


def test_major_long_short_n_validation():
    chain = _make_chain()
    with pytest.raises(ValueError):
        compute.major_long_short_gex(chain, n=0)


# ---------------------------------------------------------------------------
# Zero Gamma
# ---------------------------------------------------------------------------


def test_zero_gamma_finds_root_within_bracket():
    """Construct a chain with clear gamma flip between put-heavy below and call-heavy above."""
    strikes = np.arange(5400, 5605, 5.0, dtype=float)
    sigma = np.full(len(strikes), 0.15)
    F = 5500.0
    # Put-heavy below F (negative GEX), call-heavy above F (positive GEX)
    oi_call = np.where(strikes > F, 3000.0, 100.0)
    oi_put = np.where(strikes < F, 3000.0, 100.0)
    chain = compute.ChainSnapshot(
        strikes=strikes, iv_call=sigma, iv_put=sigma,
        oi_call=oi_call, oi_put=oi_put,
        vol_call=oi_call, vol_put=oi_put,
        forward=F, spot=F, T=4.0/(365*24), r=0.043, q=0.013,
        underlying="SPXW", expiration="2026-05-03",
    )
    zg = compute.zero_gamma(chain)
    assert np.isfinite(zg.zero_gamma)
    # The root should be near F (since OI is symmetric around F)
    assert abs(zg.zero_gamma - F) < 50.0
    # Should be within bracket
    assert zg.in_bracket
    assert zg.bracket_lo < zg.zero_gamma < zg.bracket_hi
    assert not zg.fallback_used


def test_zero_gamma_constraint_between_major_short_and_long():
    """ZG must lie between the major short (lower) and major long (upper) by volume."""
    strikes = np.arange(5400, 5605, 5.0, dtype=float)
    sigma = np.full(len(strikes), 0.15)
    F = 5500.0
    # Use volume to force constraint
    vol_c = np.where(strikes > F, 5000.0, 50.0)
    vol_p = np.where(strikes < F, 5000.0, 50.0)
    chain = compute.ChainSnapshot(
        strikes=strikes, iv_call=sigma, iv_put=sigma,
        oi_call=vol_c, oi_put=vol_p, vol_call=vol_c, vol_put=vol_p,
        forward=F, spot=F, T=4.0/(365*24), r=0.043, q=0.013,
        underlying="SPXW", expiration="2026-05-03",
    )
    longs, shorts = compute.major_long_short_gex(chain, n=3, use_volume=True)
    longs_above = [lvl.strike for lvl in longs if lvl.strike > F]
    shorts_below = [lvl.strike for lvl in shorts if lvl.strike < F]
    expected_lo = max(shorts_below) if shorts_below else min(s.strike for s in shorts)
    expected_hi = min(longs_above) if longs_above else max(s.strike for s in longs)
    zg = compute.zero_gamma(chain)
    assert expected_lo <= zg.zero_gamma <= expected_hi
    assert zg.bracket_lo == expected_lo
    assert zg.bracket_hi == expected_hi


def test_zero_gamma_no_sign_change_returns_nan_or_fallback():
    """If chain is monotonically positive/negative GEX, ZG might use fallback or NaN."""
    strikes = np.arange(5400, 5605, 5.0, dtype=float)
    sigma = np.full(len(strikes), 0.15)
    F = 5500.0
    # All call-heavy: positive GEX everywhere -> no root
    oi_c = np.full(len(strikes), 2000.0)
    oi_p = np.full(len(strikes), 100.0)
    chain = compute.ChainSnapshot(
        strikes=strikes, iv_call=sigma, iv_put=sigma,
        oi_call=oi_c, oi_put=oi_p, vol_call=oi_c, vol_put=oi_p,
        forward=F, spot=F, T=4.0/(365*24), r=0.043, q=0.013,
        underlying="SPXW", expiration="2026-05-03",
    )
    zg = compute.zero_gamma(chain)
    # All-positive chain: no negative-GEX strikes by volume -> result should be NaN with note
    assert np.isnan(zg.zero_gamma) or zg.fallback_used


# ---------------------------------------------------------------------------
# Put / Call Walls
# ---------------------------------------------------------------------------


def test_call_wall_above_F():
    strikes = np.arange(5400, 5605, 5.0, dtype=float)
    sigma = np.full(len(strikes), 0.15)
    oi_c = np.zeros(len(strikes))
    oi_c[np.argmin(np.abs(strikes - 5550))] = 5000.0  # max at 5550
    oi_c[np.argmin(np.abs(strikes - 5450))] = 9000.0  # but bigger at 5450 (below F)
    oi_p = np.zeros(len(strikes))
    chain = compute.ChainSnapshot(
        strikes=strikes, iv_call=sigma, iv_put=sigma,
        oi_call=oi_c, oi_put=oi_p, vol_call=oi_c, vol_put=oi_p,
        forward=5500.0, spot=5500.0, T=4.0/(365*24), r=0.043, q=0.013,
        underlying="SPXW", expiration="2026-05-03",
    )
    cw, pw = compute.put_call_walls(chain)
    assert cw is not None
    # Should pick 5550 (above F) not 5450 (below F)
    assert cw.strike == 5550.0
    assert cw.oi == 5000.0
    # No put OI -> no put wall
    assert pw is None


def test_put_wall_below_F():
    strikes = np.arange(5400, 5605, 5.0, dtype=float)
    sigma = np.full(len(strikes), 0.15)
    oi_p = np.zeros(len(strikes))
    oi_p[np.argmin(np.abs(strikes - 5450))] = 8000.0
    oi_p[np.argmin(np.abs(strikes - 5550))] = 12000.0  # bigger but above F -> ignored
    oi_c = np.zeros(len(strikes))
    chain = compute.ChainSnapshot(
        strikes=strikes, iv_call=sigma, iv_put=sigma,
        oi_call=oi_c, oi_put=oi_p, vol_call=oi_c, vol_put=oi_p,
        forward=5500.0, spot=5500.0, T=4.0/(365*24), r=0.043, q=0.013,
        underlying="SPXW", expiration="2026-05-03",
    )
    cw, pw = compute.put_call_walls(chain)
    assert pw is not None
    assert pw.strike == 5450.0
    assert pw.oi == 8000.0
    assert cw is None


def test_walls_handle_no_oi():
    chain = _make_chain(
        oi_call_pattern=np.zeros(41),
        oi_put_pattern=np.zeros(41),
    )
    cw, pw = compute.put_call_walls(chain)
    assert cw is None
    assert pw is None


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


def test_compute_levels_end_to_end():
    strikes = np.arange(5400, 5605, 5.0, dtype=float)
    sigma = np.full(len(strikes), 0.15)
    F = 5500.0
    # Put-heavy below F, call-heavy above F (classic 0DTE intraday pattern)
    oi_call = 100.0 + np.where(strikes > F, 2500.0 * np.exp(-((strikes - 5560) / 30.0) ** 2), 50.0)
    oi_put = 100.0 + np.where(strikes < F, 2500.0 * np.exp(-((strikes - 5440) / 30.0) ** 2), 50.0)
    vol_call = oi_call * 0.5
    vol_put = oi_put * 0.5

    chain = compute.ChainSnapshot(
        strikes=strikes, iv_call=sigma, iv_put=sigma,
        oi_call=oi_call, oi_put=oi_put, vol_call=vol_call, vol_put=vol_put,
        forward=F, spot=F, T=4.0/(365*24), r=0.043, q=0.013,
        underlying="SPXW", expiration="2026-05-03",
    )
    snap = compute.compute_levels(chain, n_major=3)
    assert snap.underlying == "SPXW"
    assert snap.forward == F
    assert snap.zero_gamma is not None
    assert np.isfinite(snap.zero_gamma.zero_gamma)
    assert snap.call_wall is not None
    assert snap.put_wall is not None
    assert snap.call_wall.strike > F
    assert snap.put_wall.strike < F
    assert len(snap.major_long_gex) == 3
    assert len(snap.major_short_gex) == 3
    assert "total_gex_volume" in snap.diagnostics
