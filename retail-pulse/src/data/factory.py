"""Builds the right `DataSource`/`RetailRepository` from environment configuration.

This is the single place that knows which backend a URL scheme maps to. To add a warehouse,
implement `DataSource` and add its scheme to `_BUILDERS`.
"""

from __future__ import annotations

from collections.abc import Callable

from config.settings import Settings, get_settings
from src.data.errors import UnsupportedDataSourceError
from src.data.repository import RetailRepository
from src.data.source import DataSource, SQLiteDataSource

_SQLITE_PREFIX = "sqlite:///"


def _build_sqlite(db_url: str) -> DataSource:
    return SQLiteDataSource(db_url[len(_SQLITE_PREFIX):])


_BUILDERS: dict[str, Callable[[str], DataSource]] = {_SQLITE_PREFIX: _build_sqlite}


def create_data_source(db_url: str) -> DataSource:
    for prefix, builder in _BUILDERS.items():
        if db_url.startswith(prefix):
            return builder(db_url)
    scheme = db_url.split(":", 1)[0]
    raise UnsupportedDataSourceError(
        f"No data source implementation for scheme {scheme!r}. Supported: "
        f"{', '.join(p.rstrip(':/') for p in _BUILDERS)}."
    )


def get_repository(settings: Settings | None = None) -> RetailRepository:
    """Repository for the active environment (or explicit `settings`, e.g. in tests)."""
    settings = settings or get_settings()
    return RetailRepository(create_data_source(settings.db_url))
