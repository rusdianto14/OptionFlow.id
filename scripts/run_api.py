"""CLI entry point for the FastAPI service.

Examples:

    uv run python scripts/run_api.py
    uv run python scripts/run_api.py --host 0.0.0.0 --port 8080

    # production-style with multiple workers
    uv run uvicorn optionflow.api:app --host 0.0.0.0 --port 8000 --workers 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

# allow running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> int:
    p = argparse.ArgumentParser(description="OptionFlow FastAPI server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    args = p.parse_args()

    uvicorn.run(
        "optionflow.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
