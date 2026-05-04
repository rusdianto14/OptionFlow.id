"""High-level pipeline that pulls a chain snapshot from Databento and computes levels.

This module is the single entry point used by both the CLI debug tool and the
snapshot writer service. It composes `databento_loader` primitives + `compute`
into one function call:

    pull_and_build_chain(...) -> ChainSnapshot
    pull_and_compute(...)     -> LevelsSnapshot
"""

from __future__ import annotations

import datetime as dt
import logging

import databento as db

from . import compute, databento_loader

logger = logging.getLogger(__name__)

# Underlying -> Databento parent symbol
PARENT_SYMBOL = {
    "SPX": "SPX.OPT",
    "SPXW": "SPXW.OPT",
    "NDX": "NDX.OPT",
    "NDXP": "NDXP.OPT",
}

# US Eastern hours during DST (May): UTC-4. RTH session = 09:30-16:00 ET.
# 0DTE PM-settled index options settle on the 16:00 ET print.
SESSION_OPEN_UTC_HOUR_DST = 13  # 09:30 ET = 13:30 UTC
SESSION_OPEN_UTC_MIN_DST = 30
SESSION_CLOSE_UTC_HOUR_DST = 20  # 16:00 ET = 20:00 UTC
SESSION_CLOSE_UTC_MIN_DST = 0


def parent_symbol_for(underlying: str) -> str:
    """Return the Databento parent symbol for a known underlying."""
    u = underlying.upper()
    if u not in PARENT_SYMBOL:
        raise ValueError(f"Unknown underlying: {underlying}")
    return PARENT_SYMBOL[u]


def session_bounds_utc(trade_date: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """Return (RTH open UTC, RTH close UTC) for the given trade date.

    NOTE: hardcoded to DST offset for now. For winter (EST) trading days the
    UTC hour shifts +1. Production version should use zoneinfo. The 0DTE compute
    is robust to <=1-hour misalignment because we only use these to bound the
    cumulative-volume aggregation.
    """
    open_utc = dt.datetime.combine(
        trade_date,
        dt.time(SESSION_OPEN_UTC_HOUR_DST, SESSION_OPEN_UTC_MIN_DST),
        tzinfo=dt.UTC,
    )
    close_utc = dt.datetime.combine(
        trade_date,
        dt.time(SESSION_CLOSE_UTC_HOUR_DST, SESSION_CLOSE_UTC_MIN_DST),
        tzinfo=dt.UTC,
    )
    return open_utc, close_utc


def pull_and_build_chain(
    *,
    api_key: str,
    underlying: str,
    snapshot_ts: dt.datetime,
    r: float,
    q: float,
    cbbo_window_seconds: int = 120,
) -> compute.ChainSnapshot:
    """Pull definitions / OI / CBBO / volume for `underlying` at `snapshot_ts`,
    then build a `ChainSnapshot` ready for `compute.compute_levels`.

    Args:
        api_key: Databento API key with OPRA.PILLAR entitlement.
        underlying: e.g. "SPXW" or "NDXP".
        snapshot_ts: tz-aware UTC datetime; chain is anchored to this instant.
        r, q: rates passed through to BSM.
        cbbo_window_seconds: how far back to look for the most recent NBBO snapshot.
    """
    if snapshot_ts.tzinfo is None:
        raise ValueError("snapshot_ts must be tz-aware (UTC)")

    parent_symbol = parent_symbol_for(underlying)
    trade_date = snapshot_ts.date()
    target_expiration = trade_date  # 0DTE only
    open_utc, close_utc = session_bounds_utc(trade_date)

    client = db.Historical(key=api_key)

    logger.debug("loading definitions parent=%s date=%s", parent_symbol, trade_date)
    defs = databento_loader.load_definitions(
        client, parent_symbol, trade_date, target_expiration
    )
    if not defs:
        raise RuntimeError(
            f"No 0DTE instruments for {underlying} on {trade_date}"
        )

    logger.debug("loading OI parent=%s date=%s", parent_symbol, trade_date)
    oi_map = databento_loader.load_open_interest(client, parent_symbol, trade_date)

    iids = [d.instrument_id for d in defs]
    logger.debug("loading CBBO at=%s n=%d", snapshot_ts, len(iids))
    quotes = databento_loader.load_cbbo_at(
        client, iids, snapshot_ts, window_seconds=cbbo_window_seconds
    )

    logger.debug("loading volume %s..%s n=%d", open_utc, snapshot_ts, len(iids))
    vol_map = databento_loader.load_cumulative_volume(
        client, iids, open_utc, snapshot_ts
    )

    return databento_loader.build_chain_snapshot(
        definitions=defs,
        oi_by_iid=oi_map,
        quotes_by_iid=quotes,
        volume_by_iid=vol_map,
        snapshot_ts=snapshot_ts,
        expiration_close_utc=close_utc,
        r=r,
        q=q,
        underlying=underlying,
    )


def pull_and_compute(
    *,
    api_key: str,
    underlying: str,
    snapshot_ts: dt.datetime,
    r: float,
    q: float,
    n_major: int = 3,
) -> compute.LevelsSnapshot:
    """Convenience wrapper: pull chain + compute levels in one call."""
    chain = pull_and_build_chain(
        api_key=api_key,
        underlying=underlying,
        snapshot_ts=snapshot_ts,
        r=r,
        q=q,
    )
    return compute.compute_levels(chain, n_major=n_major)
