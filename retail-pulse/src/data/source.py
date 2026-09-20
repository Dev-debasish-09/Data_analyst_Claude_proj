"""Data source abstraction and the SQLite implementation.

`DataSource` is the only thing the repository knows about the backend. To move to a real
warehouse, add another `DataSource` subclass (e.g. Snowflake/BigQuery/Postgres) and register
its URL scheme in `factory.py`; nothing that calls the repository changes.

Contract for implementations:
  * `read` runs a single read-only SELECT and returns a DataFrame.
  * SQL uses named parameters written as `:name` and standard, portable SQL.
  * Backend errors are translated into `src.data.errors` exceptions.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.errors import DataSourceUnavailableError, QueryError


class DataSource(ABC):
    """A read-only connection to wherever retail data lives."""

    @abstractmethod
    def read(self, sql: str, params: Mapping[str, Any] | None = None) -> pd.DataFrame:
        """Execute a SELECT with named (`:name`) parameters and return the rows."""

    @abstractmethod
    def ping(self) -> None:
        """Raise `DataSourceUnavailableError` if the source cannot be reached."""


class SQLiteDataSource(DataSource):
    """SQLite backend for the dev environment.

    A short-lived connection is opened per query and always closed. That avoids leaked
    handles and cross-thread problems (Streamlit runs callbacks on different threads) at
    negligible cost for a local file. Connections are read-only (`mode=ro`), so the app
    cannot modify the database even by mistake.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser().resolve()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        if not self._path.is_file():
            raise DataSourceUnavailableError(
                f"SQLite database not found at {self._path}. In dev, create it with "
                "`python scripts/generate_synthetic_data.py`."
            )
        try:
            return sqlite3.connect(f"{self._path.as_uri()}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            raise DataSourceUnavailableError(f"Cannot open {self._path}: {exc}") from exc

    def read(self, sql: str, params: Mapping[str, Any] | None = None) -> pd.DataFrame:
        with closing(self._connect()) as conn:
            try:
                return pd.read_sql_query(sql, conn, params=dict(params or {}))
            except (sqlite3.Error, pd.errors.DatabaseError) as exc:
                raise QueryError(f"Query failed: {exc}") from exc

    def ping(self) -> None:
        self.read("SELECT 1 AS ok")
