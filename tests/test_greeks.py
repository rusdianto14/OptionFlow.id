"""Test BSM Greeks against analytical reference values and numerical derivatives.

References for hard-coded numbers:
- Hull, "Options, Futures, and Other Derivatives", 10th ed., Examples 15.6, 15.7
- Haug (2007), "The Complete Guide to Option Pricing Formulas"
- Independent verification via QuantLib / py_vollib
"""

from __future__ import annotations

import numpy as np
import pytest

from optionflow import greeks

# ---------------------------------------------------------------------------
# Put-call parity (must hold for ANY valid pricing model)
# ---------------------------------------------------------------------------


def test_put_call_parity_atm():
    """C - P = S exp(-qT) - K exp(-rT)."""
    S, K, T, r, q, sigma = 100.0, 100.0, 0.5, 0.04, 0.02, 0.20
    c = greeks.price(S, K, T, r, q, sigma, "C")
    p = greeks.price(S, K, T, r, q, sigma, "P")
    expected = S * np.exp(-q * T) - K * np.exp(-r * T)
    assert np.isclose(c - p, expected, atol=1e-10)


def test_put_call_parity_otm():
    """Same but for OTM options."""
    for K in [80.0, 90.0, 110.0, 120.0]:
        S, T, r, q, sigma = 100.0, 0.25, 0.05, 0.015, 0.30
        c = greeks.price(S, K, T, r, q, sigma, "C")
        p = greeks.price(S, K, T, r, q, sigma, "P")
        expected = S * np.exp(-q * T) - K * np.exp(-r * T)
        assert np.isclose(c - p, expected, atol=1e-10), f"parity broken at K={K}"


# ---------------------------------------------------------------------------
# Hard-coded reference values (computed independently via QuantLib)
# ---------------------------------------------------------------------------


def test_call_price_hull_example():
    """Hull 10e Ex 15.6: S=42, K=40, r=10%, T=0.5, sigma=20%, no dividend.
    Expected call price: 4.7594 (Hull's stated value)."""
    c = greeks.price(42.0, 40.0, 0.5, 0.10, 0.0, 0.20, "C")
    assert np.isclose(c, 4.7594, atol=1e-3)


def test_put_price_hull_example():
    """Hull 10e Ex 15.6: P = 0.8086."""
    p = greeks.price(42.0, 40.0, 0.5, 0.10, 0.0, 0.20, "P")
    assert np.isclose(p, 0.8086, atol=1e-3)


def test_call_delta_hull_example():
    """Hull 10e: delta_C = N(d1) for non-div stock = N((ln(42/40)+(0.10+0.5*0.04)*0.5)/(0.20*sqrt(0.5)))
    = N(0.7693) ~ 0.7791. Hull cites 0.779."""
    d = greeks.delta(42.0, 40.0, 0.5, 0.10, 0.0, 0.20, "C")
    assert np.isclose(d, 0.7791, atol=1e-3)


def test_put_delta_relationship():
    """delta_P = delta_C - exp(-qT) (from put-call parity)."""
    S, K, T, r, q, sigma = 100.0, 100.0, 0.5, 0.04, 0.02, 0.25
    dc = greeks.delta(S, K, T, r, q, sigma, "C")
    dp = greeks.delta(S, K, T, r, q, sigma, "P")
    assert np.isclose(dc - dp, np.exp(-q * T), atol=1e-10)


def test_gamma_call_equals_gamma_put():
    """Gamma is identical for call and put."""
    # gamma() doesn't take option_type, but verify identity holds via numerical differentiation
    S, K, T, r, q, sigma = 100.0, 105.0, 0.25, 0.05, 0.02, 0.20
    g = greeks.gamma(S, K, T, r, q, sigma)
    # numerical gamma_call
    h = 0.01
    pc_up = greeks.price(S + h, K, T, r, q, sigma, "C")
    pc_mid = greeks.price(S, K, T, r, q, sigma, "C")
    pc_dn = greeks.price(S - h, K, T, r, q, sigma, "C")
    g_num_call = (pc_up - 2 * pc_mid + pc_dn) / h**2
    # numerical gamma_put
    pp_up = greeks.price(S + h, K, T, r, q, sigma, "P")
    pp_mid = greeks.price(S, K, T, r, q, sigma, "P")
    pp_dn = greeks.price(S - h, K, T, r, q, sigma, "P")
    g_num_put = (pp_up - 2 * pp_mid + pp_dn) / h**2
    assert np.isclose(g, g_num_call, atol=1e-4)
    assert np.isclose(g, g_num_put, atol=1e-4)
    assert np.isclose(g_num_call, g_num_put, atol=1e-6)


# ---------------------------------------------------------------------------
# Numerical sanity: dPrice/dS = delta, d2Price/dS2 = gamma, dPrice/dsigma = vega
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("opt", ["C", "P"])
@pytest.mark.parametrize("K", [90.0, 100.0, 110.0])
def test_delta_matches_numerical_derivative(opt: str, K: float):
    S, T, r, q, sigma = 100.0, 0.25, 0.04, 0.015, 0.20
    h = 0.001
    p_up = greeks.price(S + h, K, T, r, q, sigma, opt)
    p_dn = greeks.price(S - h, K, T, r, q, sigma, opt)
    d_num = (p_up - p_dn) / (2 * h)
    d_ana = greeks.delta(S, K, T, r, q, sigma, opt)
    assert np.isclose(d_ana, d_num, atol=1e-5)


@pytest.mark.parametrize("K", [90.0, 100.0, 110.0])
def test_gamma_matches_numerical_derivative(K: float):
    S, T, r, q, sigma = 100.0, 0.25, 0.04, 0.015, 0.20
    h = 0.05  # gamma needs larger h for stability
    p_up = greeks.price(S + h, K, T, r, q, sigma, "C")
    p_mid = greeks.price(S, K, T, r, q, sigma, "C")
    p_dn = greeks.price(S - h, K, T, r, q, sigma, "C")
    g_num = (p_up - 2 * p_mid + p_dn) / h**2
    g_ana = greeks.gamma(S, K, T, r, q, sigma)
    assert np.isclose(g_ana, g_num, rtol=1e-3)


@pytest.mark.parametrize("opt", ["C", "P"])
def test_vega_matches_numerical_derivative(opt: str):
    S, K, T, r, q, sigma = 100.0, 100.0, 0.25, 0.04, 0.015, 0.20
    h = 1e-4
    p_up = greeks.price(S, K, T, r, q, sigma + h, opt)
    p_dn = greeks.price(S, K, T, r, q, sigma - h, opt)
    v_num = (p_up - p_dn) / (2 * h)
    v_ana = greeks.vega(S, K, T, r, q, sigma)
    assert np.isclose(v_ana, v_num, atol=1e-4)


# ---------------------------------------------------------------------------
# Vectorization: passing arrays returns same shape, value-equal to scalar loop
# ---------------------------------------------------------------------------


def test_gamma_vectorized():
    Ks = np.array([90.0, 95.0, 100.0, 105.0, 110.0])
    S, T, r, q, sigma = 100.0, 0.25, 0.04, 0.015, 0.20
    g_vec = greeks.gamma(S, Ks, T, r, q, sigma)
    g_scalar = np.array([greeks.gamma(S, k, T, r, q, sigma) for k in Ks]).flatten()
    assert g_vec.shape == (5,)
    assert np.allclose(g_vec, g_scalar)


def test_delta_vectorized_per_strike_sigma():
    Ks = np.array([5800.0, 5850.0, 5900.0, 5950.0, 6000.0])
    sigmas = np.array([0.12, 0.115, 0.11, 0.115, 0.125])
    S, T, r, q = 5900.0, 1.0 / 365.0, 0.043, 0.013  # 0DTE-ish
    d_vec = greeks.delta(S, Ks, T, r, q, sigmas, "C")
    assert d_vec.shape == (5,)
    # ATM call delta (0DTE) should be ~0.5 area
    assert 0.45 < d_vec[2] < 0.55


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_zero_T_intrinsic():
    """At expiry, price = intrinsic, gamma = 0."""
    S, K, r, q, sigma = 100.0, 95.0, 0.04, 0.0, 0.20
    c = greeks.price(S, K, 0.0, r, q, sigma, "C")
    p = greeks.price(S, K, 0.0, r, q, sigma, "P")
    g = greeks.gamma(S, K, 0.0, r, q, sigma)
    assert np.isclose(c, 5.0)
    assert np.isclose(p, 0.0)
    assert np.isclose(g, 0.0)


def test_zero_T_atm_call_delta_undefined_returned_zero():
    """At T=0 ATM (S==K), delta convention here returns 0 (since S>K is false)."""
    d = greeks.delta(100.0, 100.0, 0.0, 0.04, 0.0, 0.20, "C")
    assert np.isclose(d, 0.0)


def test_zero_sigma_forward_intrinsic():
    """Zero vol: deterministic, price = max(F - K*disc_r, 0) for call."""
    S, K, T, r, q = 100.0, 90.0, 1.0, 0.05, 0.02
    c = greeks.price(S, K, T, r, q, 0.0, "C")
    expected = max(S * np.exp(-q * T) - K * np.exp(-r * T), 0.0)
    assert np.isclose(c, expected)
    g = greeks.gamma(S, K, T, r, q, 0.0)
    assert np.isclose(g, 0.0)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        greeks.price(100.0, 100.0, -1.0, 0.04, 0.0, 0.2, "C")
    with pytest.raises(ValueError):
        greeks.price(100.0, 100.0, 0.5, 0.04, 0.0, -0.1, "C")
    with pytest.raises(ValueError):
        greeks.price(0.0, 100.0, 0.5, 0.04, 0.0, 0.2, "C")
    with pytest.raises(ValueError):
        greeks.delta(100.0, 100.0, 0.5, 0.04, 0.0, 0.2, "X")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 0DTE specific: Greeks should behave reasonably as T -> 0
# ---------------------------------------------------------------------------


def test_0dte_atm_gamma_peaks():
    """ATM gamma should be much larger at 1h to expiry than at 30 days."""
    S, K, r, q, sigma = 5000.0, 5000.0, 0.04, 0.01, 0.15
    g_30d = greeks.gamma(S, K, 30.0 / 365.0, r, q, sigma)
    g_1h = greeks.gamma(S, K, 1.0 / (365.0 * 24.0), r, q, sigma)
    assert g_1h > g_30d * 5  # very strong peak


def test_0dte_otm_gamma_collapses():
    """5% OTM 0DTE gamma should be near-zero."""
    S, r, q, sigma = 5000.0, 0.04, 0.01, 0.15
    T = 1.0 / (365.0 * 24.0)
    g = greeks.gamma(S, S * 1.05, T, r, q, sigma)
    assert g < 1e-6
