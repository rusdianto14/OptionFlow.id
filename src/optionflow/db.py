"""Database layer: SQLAlchemy 2.x ORM models, engine, session factory.

Schema is intentionally minimal: a single `levels_latest` table with one row per
underlying. JSONB columns hold variable-length arrays (top-N major long/short GEX,
diagnostics blob). Latest-only mode -> UPSERT on PK, no historical retention.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

from .config import get_settings


class Base(DeclarativeBase):
    pass


class LevelsLatest(Base):
    """Latest computed snapshot per underlying.

    PK is `underlying` (e.g. "SPXW", "NDXP"). All other columns reflect the most
    recent successful computation. Writers UPSERT this row on every snapshot tick.
    """

    __tablename__ = "levels_latest"

    underlying: Mapped[str] = mapped_column(String(16), primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expiration: Mapped[str] = mapped_column(String(10), nullable=False)
    f_synth: Mapped[float] = mapped_column(Float, nullable=False)
    spot_implied: Mapped[float] = mapped_column(Float, nullable=False)
    zero_gamma: Mapped[float | None] = mapped_column(Float, nullable=True)
    zg_in_bracket: Mapped[bool] = mapped_column(nullable=False, default=False)
    zg_fallback_used: Mapped[bool] = mapped_column(nullable=False, default=False)
    zg_note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    call_wall_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    call_wall_oi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    put_wall_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    put_wall_oi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_major: Mapped[int] = mapped_column(Integer, nullable=False)
    major_long_gex: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    major_short_gex: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    """Return the singleton SQLAlchemy engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the singleton SQLAlchemy session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), expire_on_commit=False, class_=Session
        )
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a SQLAlchemy session that commits on success / rolls back on error."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create tables if they don't already exist. Idempotent."""
    Base.metadata.create_all(get_engine())


def reset_db() -> None:
    """Drop and recreate all tables. **For tests only.**"""
    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
