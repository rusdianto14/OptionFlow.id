"""Load 0DTE option chain snapshots from Databento OPRA.PILLAR.

This module supports two modes:
1. Historical: pull data for a specific snapshot timestamp (used for verification).
2. Live: subscribe to OPRA.PILLAR realtime feed (separate module, future work).

Schemas used:
- definition: instrument metadata (strike, expiry, call/put, raw_symbol, instrument_id)
- statistics: end-of-day Open Interest (stat_type=9, quantity is OI count)
- cbbo-1m: consolidated NBBO snapshots at 1-minute boundaries
- trades: cumulative volume (sum of sizes per instrument)
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import databento as db
import numpy as np
import pandas as pd

from . import compute, implied_vol, synthetic_forward

DATASET = "OPRA.PILLAR"

# Databento statistics stat_type codes (from API reference)
STAT_TYPE_OPEN_INTEREST = 9


@dataclass(frozen=True, slots=True)
class InstrumentDef:
    """Subset of the OPRA definition record we actually need."""

    instrument_id: int
    raw_symbol: str
    strike: float
    expiration: dt.date
    is_call: bool
    underlying: str


def load_definitions(
    client: db.Historical,
    parent_symbol: str,
    trade_date: dt.date,
    target_expiration: dt.date,
) -> list[InstrumentDef]:
    """Load definition records for a parent symbol on a trade date, filtered to target_expiration.

    Args:
        client: Databento historical client
        parent_symbol: e.g. "SPXW.OPT" or "NDXP.OPT"
        trade_date: the date the data is from (e.g. 2026-05-01)
        target_expiration: only return instruments expiring on this date (e.g. 2026-05-01 for 0DTE)
    """
    end_date = trade_date + dt.timedelta(days=1)
    df = client.timeseries.get_range(
        dataset=DATASET,
        schema="definition",
        symbols=[parent_symbol],
        stype_in="parent",
        start=trade_date.isoformat(),
        end=end_date.isoformat(),
    ).to_df()

    if df.empty:
        return []

    # Databento `expiration` is a Timestamp; compare date-only
    df["exp_date"] = pd.to_datetime(df["expiration"]).dt.date
    df = df[df["exp_date"] == target_expiration]

    out: list[InstrumentDef] = []
    seen_ids: set[int] = set()
    for _, row in df.iterrows():
        iid = int(row["instrument_id"])
        if iid in seen_ids:
            continue
        seen_ids.add(iid)
        # instrument_class 'C' = call, 'P' = put (string per Databento)
        ic = str(row.get("instrument_class", ""))
        is_call = ic.upper().startswith("C")
        out.append(
            InstrumentDef(
                instrument_id=iid,
                raw_symbol=str(row["raw_symbol"]),
                strike=float(row["strike_price"]),
                expiration=row["exp_date"],
                is_call=is_call,
                underlying=str(row.get("underlying", "")),
            )
        )
    return out


def load_open_interest(
    client: db.Historical,
    parent_symbol: str,
    trade_date: dt.date,
) -> dict[int, float]:
    """Load EOD open interest snapshots from the statistics schema for a trade date.

    Returns dict instrument_id -> OI count. Latest record per instrument wins.
    """
    end_date = trade_date + dt.timedelta(days=1)
    df = client.timeseries.get_range(
        dataset=DATASET,
        schema="statistics",
        symbols=[parent_symbol],
        stype_in="parent",
        start=trade_date.isoformat(),
        end=end_date.isoformat(),
    ).to_df()
    if df.empty:
        return {}

    df = df[df["stat_type"] == STAT_TYPE_OPEN_INTEREST]
    if df.empty:
        return {}

    # Latest record per instrument_id
    df = df.sort_values("ts_event").drop_duplicates(subset="instrument_id", keep="last")
    out: dict[int, float] = {
        int(iid): float(q)
        for iid, q in zip(df["instrument_id"], df["quantity"], strict=False)
    }
    return out


def load_cbbo_at(
    client: db.Historical,
    instrument_ids: list[int],
    snapshot_ts: dt.datetime,
    *,
    window_seconds: int = 60,
    chunk_size: int = 500,
) -> dict[int, tuple[float, float]]:
    """Load consolidated NBBO snapshots near snapshot_ts for a given set of instrument IDs.

    Filtering by instrument_id is far faster than pulling the entire parent feed.
    Splits requests into chunks to stay within Databento per-request limits.
    """
    if not instrument_ids:
        return {}
    start = (snapshot_ts - dt.timedelta(seconds=window_seconds)).isoformat()
    end = (snapshot_ts + dt.timedelta(seconds=1)).isoformat()

    out: dict[int, tuple[float, float]] = {}
    for i in range(0, len(instrument_ids), chunk_size):
        chunk = [str(x) for x in instrument_ids[i : i + chunk_size]]
        df = client.timeseries.get_range(
            dataset=DATASET,
            schema="cbbo-1m",
            symbols=chunk,
            stype_in="instrument_id",
            start=start,
            end=end,
        ).to_df()
        if df.empty:
            continue
        df = df.sort_values("ts_event").drop_duplicates(subset="instrument_id", keep="last")
        for _, row in df.iterrows():
            iid = int(row["instrument_id"])
            bid = float(row.get("bid_px_00", row.get("bid_px", float("nan"))))
            ask = float(row.get("ask_px_00", row.get("ask_px", float("nan"))))
            out[iid] = (bid, ask)
    return out


def load_cumulative_volume(
    client: db.Historical,
    instrument_ids: list[int],
    session_start: dt.datetime,
    session_end: dt.datetime,
    *,
    chunk_size: int = 500,
) -> dict[int, float]:
    """Cumulative volume per instrument from session_start to session_end (sums of ohlcv-1m bars)."""
    if not instrument_ids:
        return {}
    out: dict[int, float] = {}
    for i in range(0, len(instrument_ids), chunk_size):
        chunk = [str(x) for x in instrument_ids[i : i + chunk_size]]
        df = client.timeseries.get_range(
            dataset=DATASET,
            schema="ohlcv-1m",
            symbols=chunk,
            stype_in="instrument_id",
            start=session_start.isoformat(),
            end=session_end.isoformat(),
        ).to_df()
        if df.empty:
            continue
        grouped = df.groupby("instrument_id")["volume"].sum()
        for k, v in grouped.items():
            out[int(k)] = out.get(int(k), 0.0) + float(v)
    return out


# ---------------------------------------------------------------------------
# Build a ChainSnapshot from the loaded raw data
# ---------------------------------------------------------------------------


def build_chain_snapshot(
    *,
    definitions: list[InstrumentDef],
    oi_by_iid: dict[int, float],
    quotes_by_iid: dict[int, tuple[float, float]],
    volume_by_iid: dict[int, float],
    snapshot_ts: dt.datetime,
    expiration_close_utc: dt.datetime,
    r: float,
    q: float,
    underlying: str,
) -> compute.ChainSnapshot:
    """Aggregate raw Databento data into a per-strike ChainSnapshot.

    Steps:
        1. Group definitions by strike, separate call/put
        2. Compute mid price; solve IV per side
        3. Estimate synthetic forward F
        4. Return ChainSnapshot with all per-strike arrays sorted by strike asc
    """
    T = max((expiration_close_utc - snapshot_ts).total_seconds() / (365.0 * 24.0 * 3600.0), 1e-8)

    # Group by strike
    by_strike: dict[float, dict[str, InstrumentDef]] = {}
    for d in definitions:
        by_strike.setdefault(d.strike, {})["C" if d.is_call else "P"] = d

    strikes_sorted = sorted(by_strike.keys())
    n = len(strikes_sorted)
    strikes = np.array(strikes_sorted, dtype=float)

    # Initial pass: compute mids; we'll do synthetic-forward, then compute IVs
    mid_call = np.full(n, np.nan)
    mid_put = np.full(n, np.nan)
    oi_call = np.zeros(n)
    oi_put = np.zeros(n)
    vol_call = np.zeros(n)
    vol_put = np.zeros(n)

    for i, K in enumerate(strikes_sorted):
        pair = by_strike[K]
        if "C" in pair:
            iid = pair["C"].instrument_id
            bid, ask = quotes_by_iid.get(iid, (np.nan, np.nan))
            mid_call[i] = implied_vol.mid_price(bid, ask)
            oi_call[i] = oi_by_iid.get(iid, 0.0)
            vol_call[i] = volume_by_iid.get(iid, 0.0)
        if "P" in pair:
            iid = pair["P"].instrument_id
            bid, ask = quotes_by_iid.get(iid, (np.nan, np.nan))
            mid_put[i] = implied_vol.mid_price(bid, ask)
            oi_put[i] = oi_by_iid.get(iid, 0.0)
            vol_put[i] = volume_by_iid.get(iid, 0.0)

    # Estimate synthetic forward from put-call parity
    fit = synthetic_forward.estimate_forward(strikes, mid_call, mid_put, T=T, r=r, q=q)
    F = fit.forward
    if not np.isfinite(F):
        # fall back to median strike (shouldn't happen with good data)
        F = float(np.median(strikes))

    # Solve IV per call and put using the estimated F as "spot"
    iv_call = implied_vol.implied_vol_batch(mid_call, F, strikes, T, r, q, "C")
    iv_put = implied_vol.implied_vol_batch(mid_put, F, strikes, T, r, q, "P")

    # Smile-aware OTM-side preference:
    #   For K < F  -> OTM put IV is the clean signal (ITM call mid is dominated by intrinsic)
    #   For K > F  -> OTM call IV is the clean signal
    #   Same OTM IV is then used for both call and put gamma at that strike, since
    #   in BSM theory call IV == put IV (any discrepancy is just quote noise).
    iv_unified = np.full_like(strikes, np.nan, dtype=float)
    above_F = strikes > F
    iv_unified = np.where(above_F, iv_call, iv_put)
    # If preferred-side IV is missing, fall back to the other side's IV
    iv_unified = np.where(np.isfinite(iv_unified), iv_unified, np.where(above_F, iv_put, iv_call))

    # As a final fallback for strikes where both are NaN: use median of valid neighbours
    if np.isfinite(iv_unified).any():
        median_iv = float(np.nanmedian(iv_unified))
        iv_unified = np.where(np.isfinite(iv_unified), iv_unified, median_iv)

    # Use unified (smile-aware) IV for both call & put gamma; this is the
    # theoretically correct choice and avoids ITM mid-price noise.
    return compute.ChainSnapshot(
        strikes=strikes,
        iv_call=iv_unified,
        iv_put=iv_unified,
        oi_call=oi_call,
        oi_put=oi_put,
        vol_call=vol_call,
        vol_put=vol_put,
        forward=F,
        spot=fit.spot_implied if np.isfinite(fit.spot_implied) else F,
        T=T,
        r=r,
        q=q,
        underlying=underlying,
        expiration=str(definitions[0].expiration) if definitions else "",
    )
