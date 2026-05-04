"""Quick smoke test for Databento API key & OPRA entitlement."""

import os
import sys
from datetime import datetime, timedelta, timezone

import databento as db


def main() -> int:
    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        print("DATABENTO_API_KEY not set")
        return 1
    print(f"Key present: {key[:6]}...{key[-4:]} (len={len(key)})")

    hist = db.Historical(key=key)

    print("\n--- Datasets accessible ---")
    try:
        datasets = hist.metadata.list_datasets()
        for d in datasets:
            print(f"  {d}")
    except Exception as e:
        print(f"ERR list_datasets: {e}")
        return 2

    print("\n--- OPRA.PILLAR schemas ---")
    try:
        schemas = hist.metadata.list_schemas(dataset="OPRA.PILLAR")
        for s in schemas:
            print(f"  {s}")
    except Exception as e:
        print(f"ERR list_schemas OPRA: {e}")

    # Probe last available trading day for SPXW definition record
    print("\n--- Probing OPRA.PILLAR definition for SPXW ---")
    # use last known available date (system clock is likely a Sunday, last RTH = Fri)
    end = "2026-05-02"
    start = "2026-05-01"
    for sym in ["SPXW.OPT", "NDX.OPT", "NDXP.OPT", "SPX.OPT"]:
        print(f"\n  probe {sym}:")
        try:
            df = hist.timeseries.get_range(
                dataset="OPRA.PILLAR",
                schema="definition",
                symbols=[sym],
                stype_in="parent",
                start=start,
                end=end,
                limit=3,
            ).to_df()
            print(f"    rows: {len(df)}")
            if len(df) > 0:
                cols = ["raw_symbol", "instrument_class", "expiration", "strike_price", "underlying"]
                avail = [c for c in cols if c in df.columns]
                print(df[avail].head(3).to_string())
        except Exception as e:
            print(f"    ERR: {str(e)[:200]}")

    # test statistics (for OI)
    print("\n--- Probing OPRA.PILLAR statistics (OI) for SPXW ---")
    try:
        df = hist.timeseries.get_range(
            dataset="OPRA.PILLAR",
            schema="statistics",
            symbols=["SPXW.OPT"],
            stype_in="parent",
            start=start,
            end=end,
            limit=20,
        ).to_df()
        print(f"  rows: {len(df)}")
        if len(df) > 0:
            print(f"  columns: {list(df.columns)}")
            print(df.head(5).to_string(max_cols=15))
    except Exception as e:
        print(f"  ERR: {str(e)[:300]}")

    print("\n--- Live gateway reachable? ---")
    try:
        live = db.Live(key=key)
        print(f"  Live client OK: {live!r}")
    except Exception as e:
        print(f"ERR Live init: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
