"""CLI entry point for the snapshot writer service.

Examples:

    # one-shot historical replay
    uv run python scripts/run_writer.py once \
        --underlying SPXW --underlying NDXP \
        --date 2026-05-01 --time 14:00

    # forever loop, snapshot every 60 seconds (default)
    uv run python scripts/run_writer.py loop \
        --underlying SPXW --underlying NDXP

    # adjust interval / N major
    OPTIONFLOW_SNAPSHOT_INTERVAL_SECONDS=30 OPTIONFLOW_N_MAJOR=5 \
        uv run python scripts/run_writer.py loop --underlying SPXW
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

# allow running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from optionflow import snapshot_writer  # noqa: E402
from optionflow.config import get_settings  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="OptionFlow snapshot writer")
    sub = p.add_subparsers(dest="cmd", required=True)

    once = sub.add_parser("once", help="Write a single snapshot at a given timestamp")
    once.add_argument("--underlying", action="append", required=True, choices=["SPXW", "NDXP"])
    once.add_argument("--date", required=True, help="YYYY-MM-DD trade date")
    once.add_argument("--time", default="14:00", help="HH:MM ET (DST) snapshot time")

    loop = sub.add_parser("loop", help="Run forever, snapshot every interval")
    loop.add_argument("--underlying", action="append", required=True, choices=["SPXW", "NDXP"])

    return p


def main() -> int:
    args = _build_parser().parse_args()
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.cmd == "once":
        trade_date = dt.date.fromisoformat(args.date)
        hh, mm = (int(x) for x in args.time.split(":"))
        # ET (DST) -> UTC. Use timedelta to handle hours >= 20 without overflow.
        snapshot_ts = dt.datetime.combine(
            trade_date, dt.time(hh, mm), tzinfo=dt.UTC
        ) + dt.timedelta(hours=4)
        results = snapshot_writer.run_once(args.underlying, snapshot_ts, settings=settings)
        for u, snap in results.items():
            print(f"{u}: F={snap.forward:.2f} ZG={snap.zero_gamma.zero_gamma:.2f}")
        return 0

    if args.cmd == "loop":
        snapshot_writer.run_loop(args.underlying, settings=settings)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
