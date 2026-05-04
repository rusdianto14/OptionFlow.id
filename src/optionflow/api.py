"""FastAPI service: read-only `/levels/{underlying}` endpoint backed by Postgres.

Auth: shared secret `X-API-Key` header matching `OPTIONFLOW_API_KEY`.

Response shape matches the JSON contract agreed with MotiveWave / ATAS indicator
clients. Indicator clients are expected to:

  1. Poll this endpoint every 60 seconds.
  2. Read `f_synth` from the response.
  3. Read `F_live` from their own datafeed (Rithmic / CQG: ES or NQ price).
  4. Compute `basis = F_live - f_synth` and shift each strike by `basis` before
     plotting.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import LevelsLatest, get_session_factory, init_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class GEXLevelOut(BaseModel):
    """One major-GEX strike (in the response)."""

    strike: float
    gex: float
    by: str = Field(description='"volume" or "oi"')


class WallOut(BaseModel):
    """Put or Call Wall."""

    strike: float
    oi: int


class ZeroGammaOut(BaseModel):
    """Zero Gamma result with bracket diagnostics."""

    value: float | None = Field(description="Zero Gamma price level (None if not found)")
    in_bracket: bool
    fallback_used: bool
    note: str | None = None


class LevelsResponse(BaseModel):
    """Response payload for `/levels/{underlying}`."""

    underlying: str
    computed_at: datetime
    expiration: str
    f_synth: float = Field(description="Synthetic forward (cash space)")
    spot_implied: float
    zero_gamma: ZeroGammaOut
    call_wall: WallOut | None = None
    put_wall: WallOut | None = None
    n_major: int
    major_long_gex: list[GEXLevelOut]
    major_short_gex: list[GEXLevelOut]
    diagnostics: dict[str, Any]


# ---------------------------------------------------------------------------
# App & dependencies
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Ensure DB schema exists on startup. No-op if tables already present."""
    try:
        init_db()
    except Exception as e:  # don't hard-fail on startup; let the request surface DB errors
        logger.warning("init_db() failed during startup: %s", e)
    yield


app = FastAPI(
    title="OptionFlow.id",
    version="0.1.0",
    description="0DTE GEX / Zero Gamma / Put-Call Wall service",
    lifespan=_lifespan,
)


def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
) -> None:
    """Verify the X-API-Key header against the configured shared secret."""
    if not settings.api_key:
        # If no key is configured the service is open by default — this is only
        # the case during local dev when OPTIONFLOW_API_KEY is left at its
        # default ("changeme"). We still require some key in production.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key not configured",
        )
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
            headers={"WWW-Authenticate": "X-API-Key"},
        )


def get_db() -> Iterator[Session]:
    """Yield a SQLAlchemy session for one request."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_response(row: LevelsLatest) -> LevelsResponse:
    return LevelsResponse(
        underlying=row.underlying,
        computed_at=row.computed_at,
        expiration=row.expiration,
        f_synth=row.f_synth,
        spot_implied=row.spot_implied,
        zero_gamma=ZeroGammaOut(
            value=row.zero_gamma,
            in_bracket=row.zg_in_bracket,
            fallback_used=row.zg_fallback_used,
            note=row.zg_note,
        ),
        call_wall=(
            WallOut(strike=row.call_wall_strike, oi=row.call_wall_oi)
            if row.call_wall_strike is not None and row.call_wall_oi is not None
            else None
        ),
        put_wall=(
            WallOut(strike=row.put_wall_strike, oi=row.put_wall_oi)
            if row.put_wall_strike is not None and row.put_wall_oi is not None
            else None
        ),
        n_major=row.n_major,
        major_long_gex=[GEXLevelOut(**g) for g in (row.major_long_gex or [])],
        major_short_gex=[GEXLevelOut(**g) for g in (row.major_short_gex or [])],
        diagnostics=dict(row.diagnostics or {}),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", summary="Liveness probe")
def health() -> dict[str, str]:
    """Simple uptime check (no auth)."""
    return {"status": "ok"}


@app.get(
    "/levels/{underlying}",
    response_model=LevelsResponse,
    summary="Latest computed levels for an underlying",
    dependencies=[Depends(require_api_key)],
)
def get_levels(
    underlying: str,
    session: Annotated[Session, Depends(get_db)],
) -> LevelsResponse:
    """Return the latest UPSERT'ed snapshot for `{underlying}`.

    `underlying` is normalised to upper-case. Currently supports `SPXW` and `NDXP`.
    """
    u = underlying.upper()
    row = session.scalar(select(LevelsLatest).where(LevelsLatest.underlying == u))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no snapshot for underlying={u}",
        )
    return _row_to_response(row)
