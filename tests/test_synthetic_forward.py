"""Test synthetic forward estimator via put-call parity."""

from __future__ import annotations

import numpy as np
import pytest

from optionflow import greeks, synthetic_forward


def _generate_chain(
    F: float, T: float, r: float, q: float, sigma_atm: float, strikes: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Generate clean call/put mid quotes from a single sigma. Spot derived from F."""
    S = F * np.exp(-(r - q) * T)
    sigmas = np.full(len(strikes), sigma_atm)
    calls = np.array([float(greeks.price(S, k, T, r, q, sig, "C")) for k, sig in zip(strikes, sigmas, strict=False)])
    puts = np.array([float(greeks.price(S, k, T, r, q, sig, "P")) for k, sig in zip(strikes, sigmas, strict=False)])
    return calls, puts


def test_forward_recovery_clean():
    """With clean BSM quotes, recovered F should match input F to high precision."""
    F_true = 5500.0
    T, r, q = 1.0 / 365.0, 0.043, 0.013  # 1 day
    strikes = np.arange(5400, 5601, 5, dtype=float)
    calls, puts = _generate_chain(F_true, T, r, q, sigma_atm=0.15, strikes=strikes)
    fit = synthetic_forward.estimate_forward(strikes, calls, puts, T, r, q)
    assert np.isclose(fit.forward, F_true, atol=1e-6)
    assert fit.n_strikes_used > 0


def test_forward_recovery_with_noise():
    """Add tiny noise (1c) to mids; F should still be within 1bp."""
    F_true = 5500.0
    T, r, q = 4.0 / (365.0 * 24.0), 0.043, 0.013
    strikes = np.arange(5400, 5601, 5, dtype=float)
    calls, puts = _generate_chain(F_true, T, r, q, sigma_atm=0.15, strikes=strikes)
    rng = np.random.default_rng(42)
    calls = calls + rng.uniform(-0.01, 0.01, len(calls))
    puts = puts + rng.uniform(-0.01, 0.01, len(puts))
    fit = synthetic_forward.estimate_forward(strikes, calls, puts, T, r, q)
    assert abs(fit.forward - F_true) / F_true < 1e-4  # < 1 bp


def test_forward_recovery_with_smile():
    """Smile vol shouldn't break parity since C-P doesn't depend on sigma."""
    F_true = 5500.0
    T, r, q = 1.0 / 365.0, 0.043, 0.013
    strikes = np.arange(5400, 5601, 5, dtype=float)
    S = F_true * np.exp(-(r - q) * T)
    # smile: lower strikes have higher IV
    sigmas = 0.20 + 0.0001 * (5500 - strikes)
    calls = np.array([float(greeks.price(S, k, T, r, q, s, "C")) for k, s in zip(strikes, sigmas, strict=False)])
    puts = np.array([float(greeks.price(S, k, T, r, q, s, "P")) for k, s in zip(strikes, sigmas, strict=False)])
    fit = synthetic_forward.estimate_forward(strikes, calls, puts, T, r, q)
    assert np.isclose(fit.forward, F_true, atol=1e-3)


def test_forward_with_invalid_quotes_some_strikes():
    """Strikes with NaN quotes should be excluded; F still recoverable."""
    F_true = 5500.0
    T, r, q = 1.0 / 365.0, 0.043, 0.013
    strikes = np.arange(5400, 5601, 5, dtype=float)
    calls, puts = _generate_chain(F_true, T, r, q, 0.15, strikes)
    # corrupt a few
    calls[0] = np.nan
    puts[5] = np.nan
    calls[10] = -1.0  # invalid
    fit = synthetic_forward.estimate_forward(strikes, calls, puts, T, r, q)
    assert np.isclose(fit.forward, F_true, atol=1e-6)


def test_too_few_valid_pairs_returns_nan():
    strikes = np.array([100.0, 105.0, 110.0])
    calls = np.array([np.nan, 1.5, np.nan])
    puts = np.array([np.nan, 0.8, np.nan])
    fit = synthetic_forward.estimate_forward(strikes, calls, puts, T=0.01, r=0.04, q=0.01)
    assert np.isnan(fit.forward)
    assert fit.n_strikes_used == 0


def test_zero_T_raises():
    with pytest.raises(ValueError):
        synthetic_forward.estimate_forward(
            np.array([100.0]), np.array([1.0]), np.array([1.0]), T=0.0, r=0.04, q=0.01
        )


def test_spot_implied_consistency():
    """spot_implied = forward * exp(-(r-q)T)."""
    F_true = 5500.0
    T, r, q = 0.5 / 365.0, 0.043, 0.013
    strikes = np.arange(5400, 5601, 5, dtype=float)
    calls, puts = _generate_chain(F_true, T, r, q, 0.15, strikes)
    fit = synthetic_forward.estimate_forward(strikes, calls, puts, T, r, q)
    assert np.isclose(fit.spot_implied, fit.forward * np.exp(-(r - q) * T))
