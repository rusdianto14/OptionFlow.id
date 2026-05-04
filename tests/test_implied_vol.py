"""Test implied vol solver: roundtrip price -> sigma -> price."""

from __future__ import annotations

import numpy as np
import pytest

from optionflow import greeks, implied_vol

# ---------------------------------------------------------------------------
# Roundtrip: price(sigma) -> implied_vol -> sigma
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("opt", ["C", "P"])
@pytest.mark.parametrize("sigma_true", [0.05, 0.10, 0.20, 0.50, 1.20])
@pytest.mark.parametrize("moneyness", [0.90, 0.95, 1.00, 1.05, 1.10])
def test_iv_roundtrip(opt: str, sigma_true: float, moneyness: float):
    S, T, r, q = 100.0, 0.25, 0.04, 0.015
    K = S * moneyness
    # Generate a "market" price from the true sigma
    p_true = float(greeks.price(S, K, T, r, q, sigma_true, opt))  # type: ignore[arg-type]
    if p_true < 0.001:  # too far OTM, vega collapses; skip
        pytest.skip(f"price too small: {p_true}")
    sigma_recovered = implied_vol.implied_vol_one(
        market_price=p_true, S=S, K=K, T=T, r=r, q=q, opt=opt  # type: ignore[arg-type]
    )
    assert np.isclose(sigma_recovered, sigma_true, atol=1e-4), (
        f"opt={opt}, sigma_true={sigma_true}, K={K}, recovered={sigma_recovered}"
    )


# ---------------------------------------------------------------------------
# 0DTE specific: short T should still solve cleanly for ATM and near-ATM
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hours_to_expiry", [6.0, 2.0, 1.0, 0.25])
def test_iv_0dte_atm(hours_to_expiry: float):
    S = 5500.0
    K = 5500.0
    T = hours_to_expiry / (365.0 * 24.0)
    r, q = 0.043, 0.013
    sigma_true = 0.15
    p = float(greeks.price(S, K, T, r, q, sigma_true, "C"))
    sigma_recovered = implied_vol.implied_vol_one(p, S, K, T, r, q, "C")
    assert np.isclose(sigma_recovered, sigma_true, atol=1e-3)


@pytest.mark.parametrize("offset_pct", [-0.005, -0.002, 0.0, 0.002, 0.005])
def test_iv_0dte_near_atm(offset_pct: float):
    S = 5500.0
    K = S * (1 + offset_pct)
    T = 4.0 / (365.0 * 24.0)  # 4 hours
    r, q = 0.043, 0.013
    sigma_true = 0.18
    p = float(greeks.price(S, K, T, r, q, sigma_true, "C"))
    if p < 0.005:
        pytest.skip("price collapsed")
    sigma_rec = implied_vol.implied_vol_one(p, S, K, T, r, q, "C")
    assert np.isclose(sigma_rec, sigma_true, atol=2e-3)


# ---------------------------------------------------------------------------
# Edge cases: invalid inputs, arbitrage-violating prices
# ---------------------------------------------------------------------------


def test_iv_below_intrinsic_returns_nan():
    """Price below intrinsic violates no-arbitrage; should return NaN."""
    S, K, T, r, q = 100.0, 90.0, 0.25, 0.04, 0.015
    intrinsic = max(S * np.exp(-q * T) - K * np.exp(-r * T), 0.0)
    bad_price = intrinsic - 0.5
    sigma = implied_vol.implied_vol_one(bad_price, S, K, T, r, q, "C")
    assert np.isnan(sigma)


def test_iv_zero_or_negative_price_returns_nan():
    assert np.isnan(implied_vol.implied_vol_one(0.0, 100.0, 100.0, 0.25, 0.04, 0.015, "C"))
    assert np.isnan(implied_vol.implied_vol_one(-1.0, 100.0, 100.0, 0.25, 0.04, 0.015, "C"))


def test_iv_zero_T_returns_nan():
    assert np.isnan(implied_vol.implied_vol_one(5.0, 100.0, 95.0, 0.0, 0.04, 0.015, "C"))


def test_iv_above_upper_bound_returns_nan():
    """Price above S*exp(-qT) for call violates no-arbitrage."""
    S, K, T, r, q = 100.0, 90.0, 0.25, 0.04, 0.015
    ub = S * np.exp(-q * T)
    sigma = implied_vol.implied_vol_one(ub + 1.0, S, K, T, r, q, "C")
    assert np.isnan(sigma)


# ---------------------------------------------------------------------------
# Vectorized batch
# ---------------------------------------------------------------------------


def test_iv_batch():
    S, T, r, q = 100.0, 0.25, 0.04, 0.015
    Ks = np.array([90.0, 95.0, 100.0, 105.0, 110.0])
    sigmas_true = np.array([0.22, 0.21, 0.20, 0.21, 0.22])  # smile-ish
    prices = np.array([float(greeks.price(S, K, T, r, q, s, "C")) for K, s in zip(Ks, sigmas_true, strict=False)])
    rec = implied_vol.implied_vol_batch(prices, S, Ks, T, r, q, "C")
    assert np.allclose(rec, sigmas_true, atol=1e-4)


# ---------------------------------------------------------------------------
# mid_price filter
# ---------------------------------------------------------------------------


def test_mid_price_basic():
    assert implied_vol.mid_price(1.0, 1.10) == pytest.approx(1.05)


def test_mid_price_invalid():
    assert np.isnan(implied_vol.mid_price(0.0, 1.0))
    assert np.isnan(implied_vol.mid_price(1.0, 0.0))
    assert np.isnan(implied_vol.mid_price(1.0, 0.9))  # ask <= bid
    assert np.isnan(implied_vol.mid_price(np.nan, 1.0))


def test_mid_price_wide_spread_rejected():
    # bid=0.10, ask=0.50 -> mid=0.30, spread=0.40 -> 133% of mid -> rejected with default 50%
    assert np.isnan(implied_vol.mid_price(0.10, 0.50, max_spread_pct=0.50))


def test_mid_price_tight_spread_accepted():
    # bid=10.0 ask=10.10 -> mid=10.05 spread=0.10 -> ~1% of mid -> ok
    assert implied_vol.mid_price(10.0, 10.10) == pytest.approx(10.05)
