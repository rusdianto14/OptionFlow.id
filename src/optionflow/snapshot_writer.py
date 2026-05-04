"""Snapshot writer: pull chain from Databento, compute levels, UPSERT to Postgres.

The writer is engine-agnostic: it does not introduce any new math; it composes
existing modules (pipeline -> compute -> db).

Two modes are supported:

  - one-shot (`run_once`): pulls the option chain at a specific timestamp using
    Databento's historical batch APIs. Useful for backfill, testing, and weekend
    operation when the live feed is closed.

  - loop (`run_loop`): wakes every `snapshot_interval_seconds` and snapshots
    "now". Inside this loop the historical APIs lag a few seconds behind real
    time but are sufficient for paper testing while we wire up live feed.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import pipeline
from .compute import LevelsSnapshot, compute_levels
from .config import Settings, get_settings
from .db import LevelsLatest, init_db, session_scope

logger = logging.getLogger(__name__)


def _safe_float_or_none(x: float) -> float | None:
    if x is None:
        return None
    if not math.isfinite(x):
        return None
    return float(x)


def _levels_snapshot_to_db_row(
    snap: LevelsSnapshot, computed_at: datetime, n_major: int
) -> dict:
    """Translate a computed LevelsSnapshot into a dict suitable for UPSERT."""
    return {
        "underlying": snap.underlying,
        "computed_at": computed_at,
        "expiration": snap.expiration,
        "f_synth": float(snap.forward),
        "spot_implied": float(snap.spot_implied),
        "zero_gamma": _safe_float_or_none(snap.zero_gamma.zero_gamma),
        "zg_in_bracket": bool(snap.zero_gamma.in_bracket),
        "zg_fallback_used": bool(snap.zero_gamma.fallback_used),
        "zg_note": (snap.zero_gamma.note or None),
        "call_wall_strike": float(snap.call_wall.strike) if snap.call_wall else None,
        "call_wall_oi": int(snap.call_wall.oi) if snap.call_wall else None,
        "put_wall_strike": float(snap.put_wall.strike) if snap.put_wall else None,
        "put_wall_oi": int(snap.put_wall.oi) if snap.put_wall else None,
        "n_major": int(n_major),
        "major_long_gex": [asdict(g) for g in snap.major_long_gex],
        "major_short_gex": [asdict(g) for g in snap.major_short_gex],
        "diagnostics": {k: float(v) for k, v in snap.diagnostics.items()},
    }


def upsert_snapshot(snap: LevelsSnapshot, computed_at: datetime, n_major: int) -> None:
    """UPSERT a snapshot row into `levels_latest` keyed by `underlying`."""
    row = _levels_snapshot_to_db_row(snap, computed_at, n_major)
    with session_scope() as session:
        stmt = pg_insert(LevelsLatest).values(**row)
        update_cols = {c: stmt.excluded[c] for c in row if c != "underlying"}
        stmt = stmt.on_conflict_do_update(
            index_elements=[LevelsLatest.underlying],
            set_=update_cols,
        )
        session.execute(stmt)


def compute_and_write(
    underlying: str,
    snapshot_ts: datetime,
    settings: Settings | None = None,
) -> LevelsSnapshot:
    """Pull chain at `snapshot_ts`, compute levels, write to DB, return snapshot."""
    settings = settings or get_settings()
    chain = pipeline.pull_and_build_chain(
        api_key=settings.databento_api_key,
        underlying=underlying,
        snapshot_ts=snapshot_ts,
        r=settings.r,
        q=settings.q_for(underlying),
    )
    snap = compute_levels(chain, n_major=settings.n_major)
    computed_at = snapshot_ts.astimezone(UTC)
    upsert_snapshot(snap, computed_at=computed_at, n_major=settings.n_major)
    zg = snap.zero_gamma.zero_gamma
    logger.info(
        "wrote snapshot underlying=%s F=%.2f ZG=%s CW=%s PW=%s",
        snap.underlying,
        snap.forward,
        f"{zg:.2f}" if math.isfinite(zg) else "NaN",
        f"{snap.call_wall.strike:.0f}" if snap.call_wall else "None",
        f"{snap.put_wall.strike:.0f}" if snap.put_wall else "None",
    )
    return snap


def run_once(
    underlyings: Sequence[str],
    snapshot_ts: datetime,
    settings: Settings | None = None,
) -> dict[str, LevelsSnapshot]:
    """Compute & UPSERT a single snapshot for each underlying."""
    settings = settings or get_settings()
    init_db()
    out: dict[str, LevelsSnapshot] = {}
    for u in underlyings:
        try:
            out[u] = compute_and_write(u, snapshot_ts, settings)
        except Exception as e:
            logger.exception("failed snapshot for %s: %s", u, e)
    return out


def run_loop(
    underlyings: Sequence[str],
    settings: Settings | None = None,
) -> None:
    """Forever loop: snapshot every `snapshot_interval_seconds`."""
    settings = settings or get_settings()
    init_db()
    interval = settings.snapshot_interval_seconds
    logger.info(
        "starting snapshot loop underlyings=%s interval=%ds",
        list(underlyings),
        interval,
    )
    while True:
        snapshot_ts = datetime.now(UTC)
        for u in underlyings:
            try:
                compute_and_write(u, snapshot_ts, settings)
            except Exception as e:
                logger.exception("snapshot failed for %s: %s", u, e)
        elapsed = (datetime.now(UTC) - snapshot_ts).total_seconds()
        sleep_for = max(0.0, interval - elapsed)
        time.sleep(sleep_for)
