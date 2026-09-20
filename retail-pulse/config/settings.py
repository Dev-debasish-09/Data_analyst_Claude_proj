"""Environment-aware settings for Retail Pulse.

The active environment is chosen with RETAIL_PULSE_ENV (dev | staging | prod).
Everything else comes from environment variables, with safe defaults for dev only.
Staging and prod refuse to start without an explicit DB URL and API key, so a
misconfigured deployment can never silently fall back to the synthetic dev database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

try:  # .env is a local-development convenience; real environments set variables directly.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class ConfigError(RuntimeError):
    """Raised when required settings are missing for the active environment."""


_DEFAULT_DEV_DB_URL = "sqlite:///./local_dev.db"
_DEFAULT_MODEL = "claude-sonnet-5"
_DEFAULT_LOG_LEVEL = {
    Environment.DEV: "DEBUG",
    Environment.STAGING: "INFO",
    Environment.PROD: "WARNING",
}


@dataclass(frozen=True)
class Settings:
    env: Environment
    db_url: str
    anthropic_api_key: str | None
    model: str
    log_level: str

    @property
    def is_dev(self) -> bool:
        return self.env is Environment.DEV

    def __repr__(self) -> str:  # never leak secrets into logs
        key = "***" if self.anthropic_api_key else None
        return (
            f"Settings(env={self.env.value!r}, db_url={self.db_url!r}, "
            f"anthropic_api_key={key!r}, model={self.model!r}, log_level={self.log_level!r})"
        )


def load_settings() -> Settings:
    raw_env = os.getenv("RETAIL_PULSE_ENV", "dev").strip().lower()
    try:
        env = Environment(raw_env)
    except ValueError:
        valid = ", ".join(e.value for e in Environment)
        raise ConfigError(f"Invalid RETAIL_PULSE_ENV={raw_env!r}; expected one of: {valid}") from None

    db_url = os.getenv("RETAIL_PULSE_DB_URL")
    api_key = os.getenv("ANTHROPIC_API_KEY") or None

    if env is Environment.DEV:
        db_url = db_url or _DEFAULT_DEV_DB_URL
    else:
        missing = [
            name
            for name, value in (("RETAIL_PULSE_DB_URL", db_url), ("ANTHROPIC_API_KEY", api_key))
            if not value
        ]
        if missing:
            raise ConfigError(f"{env.value} requires environment variables: {', '.join(missing)}")

    return Settings(
        env=env,
        db_url=db_url,
        anthropic_api_key=api_key,
        model=os.getenv("RETAIL_PULSE_MODEL", _DEFAULT_MODEL),
        log_level=os.getenv("RETAIL_PULSE_LOG_LEVEL", _DEFAULT_LOG_LEVEL[env]).upper(),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor; call `get_settings.cache_clear()` in tests after changing env vars."""
    return load_settings()
