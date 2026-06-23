"""Application configuration loaded from environment variables.

Every value is optional. With nothing set the app runs fully offline using the
bundled seed data and the background scheduler stays disabled.
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.app_name: str = os.getenv("APP_NAME", "One-I")
        self.database_url: str = os.getenv("DATABASE_URL", "sqlite:///clarity.db")
        self.gnews_api_key: str = os.getenv("GNEWS_API_KEY", "").strip()
        self.enable_scheduler: bool = _as_bool(os.getenv("ENABLE_SCHEDULER"), False)
        self.ingest_interval_hours: int = int(os.getenv("INGEST_INTERVAL_HOURS", "6"))
        self.reddit_user_agent: str = os.getenv(
            "REDDIT_USER_AGENT", "one-i-news-intel/0.1"
        )

    @property
    def tagline(self) -> str:
        return "Read one story. Understand everything."


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
