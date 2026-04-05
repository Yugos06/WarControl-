from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("WARCONTROL_DB_PATH", "data/warcontrol.db")
    ingest_key: str | None = os.getenv("WARCONTROL_INGEST_KEY")
    allow_open_ingest: bool = _env_bool("WARCONTROL_ALLOW_OPEN_INGEST", False)
    web_origins: list[str] = _env_list("WARCONTROL_WEB_ORIGINS", ["*"])


settings = Settings()
