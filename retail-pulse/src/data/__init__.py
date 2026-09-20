"""Data access layer. Import from here; callers never touch a backend directly."""

from src.data.errors import (
    DataAccessError,
    DataSourceUnavailableError,
    QueryError,
    UnsupportedDataSourceError,
)
from src.data.factory import create_data_source, get_repository
from src.data.repository import RetailRepository
from src.data.source import DataSource, SQLiteDataSource

__all__ = [
    "DataAccessError",
    "DataSource",
    "DataSourceUnavailableError",
    "QueryError",
    "RetailRepository",
    "SQLiteDataSource",
    "UnsupportedDataSourceError",
    "create_data_source",
    "get_repository",
]
