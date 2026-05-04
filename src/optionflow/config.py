"""Centralised configuration for OptionFlow services.

All env vars are prefixed `OPTIONFLOW_` (or set as named env vars). Loaded once at
process startup via `Settings()`.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings populated from environment variables.

    Required env vars:
      DATABENTO_API_KEY  - Databento API key with OPRA.PILLAR entitlement
      DATABASE_URL       - SQLAlchemy URL, e.g. postgresql+psycopg://user:pw@localhost/optionflow
      OPTIONFLOW_API_KEY - Shared secret expected in `X-API-Key` request header

    Optional env vars (with defaults):
      OPTIONFLOW_R                - risk-free rate (continuous), default 0.0430
      OPTIONFLOW_Q_SPX            - SPX dividend yield, default 0.0130
      OPTIONFLOW_Q_NDX            - NDX dividend yield, default 0.0070
      OPTIONFLOW_N_MAJOR          - top-N for major long/short GEX, default 3
      OPTIONFLOW_SNAPSHOT_INTERVAL_SECONDS - writer poll interval, default 60
      OPTIONFLOW_LOG_LEVEL        - INFO / DEBUG / WARNING, default INFO
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    databento_api_key: str = Field(default="", alias="DATABENTO_API_KEY")
    database_url: str = Field(
        default="postgresql+psycopg://optionflow:optionflow@localhost:5432/optionflow",
        alias="DATABASE_URL",
    )
    api_key: str = Field(default="changeme", alias="OPTIONFLOW_API_KEY")

    r: float = Field(default=0.0430, alias="OPTIONFLOW_R")
    q_spx: float = Field(default=0.0130, alias="OPTIONFLOW_Q_SPX")
    q_ndx: float = Field(default=0.0070, alias="OPTIONFLOW_Q_NDX")
    n_major: int = Field(default=3, alias="OPTIONFLOW_N_MAJOR", ge=1, le=5)
    snapshot_interval_seconds: int = Field(
        default=60, alias="OPTIONFLOW_SNAPSHOT_INTERVAL_SECONDS", ge=1
    )
    log_level: str = Field(default="INFO", alias="OPTIONFLOW_LOG_LEVEL")

    def q_for(self, underlying: str) -> float:
        """Lookup dividend yield for a given underlying (case-insensitive)."""
        u = underlying.upper()
        if u in {"SPX", "SPXW"}:
            return self.q_spx
        if u in {"NDX", "NDXP"}:
            return self.q_ndx
        raise ValueError(f"Unknown underlying for q lookup: {underlying}")


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
