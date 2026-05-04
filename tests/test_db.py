"""DB layer tests: schema creation, UPSERT idempotency, JSON roundtrip."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pytest
from sqlalchemy import select

from optionflow import compute, db, snapshot_writer


def _fake_chain() -> compute.ChainSnapshot:
    """Build a tiny synthetic chain for round-trip tests."""
    strikes = np.array([5095.0, 5100.0, 5105.0, 5110.0, 5115.0])
    iv = np.full_like(strikes, 0.20)
    oi_call = np.array([100.0, 200.0, 800.0, 400.0, 50.0])
    oi_put = np.array([60.0, 500.0, 700.0, 100.0, 30.0])
    vol_call = np.array([10.0, 80.0, 300.0, 50.0, 5.0])
    vol_put = np.array([8.0, 200.0, 250.0, 20.0, 3.0])
    return compute.ChainSnapshot(
        strikes=strikes,
        iv_call=iv,
        iv_put=iv,
        oi_call=oi_call,
        oi_put=oi_put,
        vol_call=vol_call,
        vol_put=vol_put,
        forward=5105.0,
        spot=5104.5,
        T=2.0 / (365.0 * 24.0),  # 2 hours
        r=0.043,
        q=0.013,
        underlying="SPXW",
        expiration="2026-05-01",
    )


@pytest.mark.usefixtures("db_session")
def test_init_db_creates_tables(db_session):
    """init_db should create the levels_latest table; subsequent calls are no-ops."""
    db.init_db()  # idempotent
    # query empty table
    result = db_session.execute(select(db.LevelsLatest)).all()
    assert result == []


def test_upsert_inserts_then_updates(db_session):
    snap = compute.compute_levels(_fake_chain(), n_major=3)
    ts = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)

    snapshot_writer.upsert_snapshot(snap, computed_at=ts, n_major=3)

    rows = db_session.execute(select(db.LevelsLatest)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.underlying == "SPXW"
    assert row.f_synth == pytest.approx(5105.0)
    assert isinstance(row.major_long_gex, list)
    assert isinstance(row.major_short_gex, list)
    assert all("strike" in g and "gex" in g and "by" in g for g in row.major_long_gex)

    first_updated_at = row.updated_at
    assert first_updated_at is not None

    # second UPSERT same underlying -> still only one row, with refreshed values
    import time as _time

    _time.sleep(0.05)  # ensure func.now() advances measurably between UPSERTs
    snap2 = compute.compute_levels(_fake_chain(), n_major=3)
    ts2 = datetime(2026, 5, 1, 18, 1, tzinfo=UTC)
    snapshot_writer.upsert_snapshot(snap2, computed_at=ts2, n_major=3)

    db_session.expire_all()
    rows = db_session.execute(select(db.LevelsLatest)).scalars().all()
    assert len(rows) == 1
    assert rows[0].computed_at == ts2
    # updated_at must advance on UPSERT (Devin Review BUG_..._0001 regression)
    assert rows[0].updated_at > first_updated_at


def test_upsert_two_underlyings_yields_two_rows(db_session):
    chain1 = _fake_chain()

    # Build a synthetic NDXP chain by tweaking the fake one
    strikes = np.array([22000.0, 22050.0, 22100.0, 22150.0, 22200.0])
    iv = np.full_like(strikes, 0.18)
    chain2 = compute.ChainSnapshot(
        strikes=strikes,
        iv_call=iv,
        iv_put=iv,
        oi_call=np.array([10.0, 20.0, 80.0, 40.0, 5.0]),
        oi_put=np.array([6.0, 50.0, 70.0, 10.0, 3.0]),
        vol_call=np.array([1.0, 8.0, 30.0, 5.0, 0.5]),
        vol_put=np.array([0.8, 20.0, 25.0, 2.0, 0.3]),
        forward=22100.0,
        spot=22099.0,
        T=2.0 / (365.0 * 24.0),
        r=0.043,
        q=0.007,
        underlying="NDXP",
        expiration="2026-05-01",
    )
    ts = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)

    snap1 = compute.compute_levels(chain1, n_major=3)
    snap2 = compute.compute_levels(chain2, n_major=3)
    snapshot_writer.upsert_snapshot(snap1, computed_at=ts, n_major=3)
    snapshot_writer.upsert_snapshot(snap2, computed_at=ts, n_major=3)

    rows = db_session.execute(select(db.LevelsLatest)).scalars().all()
    assert len(rows) == 2
    assert {r.underlying for r in rows} == {"SPXW", "NDXP"}


def test_walls_serialize_correctly(db_session):
    snap = compute.compute_levels(_fake_chain(), n_major=3)
    ts = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
    snapshot_writer.upsert_snapshot(snap, computed_at=ts, n_major=3)

    row = db_session.execute(select(db.LevelsLatest)).scalar_one()
    if snap.call_wall is not None:
        assert row.call_wall_strike == pytest.approx(snap.call_wall.strike)
        assert row.call_wall_oi == int(snap.call_wall.oi)
    if snap.put_wall is not None:
        assert row.put_wall_strike == pytest.approx(snap.put_wall.strike)
        assert row.put_wall_oi == int(snap.put_wall.oi)


def test_zero_gamma_nan_serializes_as_null(db_session):
    """If ZG is NaN, the DB column should be NULL (not NaN)."""
    chain = _fake_chain()
    # Make all OI flat positive so ZG fails to find a sign change in any reasonable bracket
    chain = compute.ChainSnapshot(
        strikes=chain.strikes,
        iv_call=chain.iv_call,
        iv_put=chain.iv_put,
        oi_call=np.full_like(chain.strikes, 100.0),
        oi_put=np.zeros_like(chain.strikes),
        vol_call=np.full_like(chain.strikes, 100.0),
        vol_put=np.zeros_like(chain.strikes),
        forward=chain.forward,
        spot=chain.spot,
        T=chain.T,
        r=chain.r,
        q=chain.q,
        underlying=chain.underlying,
        expiration=chain.expiration,
    )
    snap = compute.compute_levels(chain, n_major=3)
    ts = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
    snapshot_writer.upsert_snapshot(snap, computed_at=ts, n_major=3)

    row = db_session.execute(select(db.LevelsLatest)).scalar_one()
    # When chain is all-positive GEX there are no negative strikes, so ZG result is NaN
    # and DB should store NULL.
    if math.isnan(snap.zero_gamma.zero_gamma):
        assert row.zero_gamma is None
