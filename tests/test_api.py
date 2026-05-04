"""FastAPI endpoint tests using TestClient."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from fastapi.testclient import TestClient

from optionflow import compute, snapshot_writer


@pytest.fixture
def client(db_session, monkeypatch):
    """Build a TestClient with a fixed API key."""
    monkeypatch.setenv("OPTIONFLOW_API_KEY", "test-key-123")

    # Reset cached settings so the new env var is picked up
    from optionflow import config as cfg

    cfg._settings = None

    from optionflow.api import app

    return TestClient(app)


def _seed_spxw(n_major: int = 3) -> None:
    strikes = np.array([5095.0, 5100.0, 5105.0, 5110.0, 5115.0])
    iv = np.full_like(strikes, 0.20)
    chain = compute.ChainSnapshot(
        strikes=strikes,
        iv_call=iv,
        iv_put=iv,
        oi_call=np.array([100.0, 200.0, 800.0, 400.0, 50.0]),
        oi_put=np.array([60.0, 500.0, 700.0, 100.0, 30.0]),
        vol_call=np.array([10.0, 80.0, 300.0, 50.0, 5.0]),
        vol_put=np.array([8.0, 200.0, 250.0, 20.0, 3.0]),
        forward=5105.0,
        spot=5104.5,
        T=2.0 / (365.0 * 24.0),
        r=0.043,
        q=0.013,
        underlying="SPXW",
        expiration="2026-05-01",
    )
    snap = compute.compute_levels(chain, n_major=n_major)
    ts = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
    snapshot_writer.upsert_snapshot(snap, computed_at=ts, n_major=n_major)


def test_health_open(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_levels_requires_api_key(client):
    _seed_spxw()
    r = client.get("/levels/SPXW")
    assert r.status_code == 401


def test_levels_invalid_api_key(client):
    _seed_spxw()
    r = client.get("/levels/SPXW", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_levels_returns_snapshot(client):
    _seed_spxw()
    r = client.get("/levels/SPXW", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["underlying"] == "SPXW"
    assert data["expiration"] == "2026-05-01"
    assert data["f_synth"] == pytest.approx(5105.0)
    assert "zero_gamma" in data
    assert "value" in data["zero_gamma"]
    assert "in_bracket" in data["zero_gamma"]
    assert isinstance(data["major_long_gex"], list)
    assert isinstance(data["major_short_gex"], list)
    assert data["n_major"] == 3
    # diagnostics keys exist
    assert "total_gex_volume" in data["diagnostics"]


def test_levels_404_when_missing(client):
    # nothing seeded
    r = client.get("/levels/SPXW", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 404


def test_levels_lowercase_normalised(client):
    _seed_spxw()
    r = client.get("/levels/spxw", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200
    assert r.json()["underlying"] == "SPXW"


def test_majors_have_correct_shape(client):
    _seed_spxw(n_major=3)
    r = client.get("/levels/SPXW", headers={"X-API-Key": "test-key-123"})
    data = r.json()
    for lvl in data["major_long_gex"]:
        assert set(lvl.keys()) == {"strike", "gex", "by"}
        assert lvl["by"] == "volume"
        assert lvl["gex"] > 0
    for lvl in data["major_short_gex"]:
        assert set(lvl.keys()) == {"strike", "gex", "by"}
        assert lvl["by"] == "volume"
        assert lvl["gex"] < 0
