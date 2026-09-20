"""Exceptions raised by the data access layer.

Callers should catch `DataAccessError` (or a subclass) and never backend-specific errors
such as `sqlite3.Error`, so the backend can be swapped without touching calling code.
"""


class DataAccessError(Exception):
    """Base class for all data access failures."""


class DataSourceUnavailableError(DataAccessError):
    """The data source could not be reached or opened (missing file, bad credentials, ...)."""


class UnsupportedDataSourceError(DataAccessError):
    """The configured DB URL uses a backend this project has no implementation for."""


class QueryError(DataAccessError):
    """A query failed to execute or was invalid."""
