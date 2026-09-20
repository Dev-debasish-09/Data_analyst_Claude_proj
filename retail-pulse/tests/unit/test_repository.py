"""Data access layer: typed queries, filters, and error handling."""

from __future__ import annotations

import pytest

from src.data import (
    DataAccessError,
    DataSourceUnavailableError,
    QueryError,
    SQLiteDataSource,
    UnsupportedDataSourceError,
    create_data_source,
)
from src.data.repository import (
    HOUSEHOLD_COLUMNS,
    LOOKUP_DAY_COLUMNS,
    PROMO_COLUMNS,
    STORE_COLUMNS,
    TXN_HDR_COLUMNS,
    TXN_ITM_COLUMNS,
    UPC_COLUMNS,
)


@pytest.mark.parametrize("method, columns", [
    ("get_txn_hdr", TXN_HDR_COLUMNS), ("get_txn_itm", TXN_ITM_COLUMNS), ("get_upcs", UPC_COLUMNS),
    ("get_stores", STORE_COLUMNS), ("get_lookup_days", LOOKUP_DAY_COLUMNS),
    ("get_household_segmentation", HOUSEHOLD_COLUMNS), ("get_promos", PROMO_COLUMNS),
])  # fmt: skip
def test_every_table_returns_exactly_its_columns(repo, method, columns):
    df = getattr(repo, method)()
    assert tuple(df.columns) == columns
    assert len(df) > 0


def test_row_counts_match_the_database(repo, q):
    assert len(repo.get_stores()) == q("SELECT COUNT(*) AS n FROM store")["n"][0]
    assert len(repo.get_txn_hdr()) == q("SELECT COUNT(*) AS n FROM txn_hdr")["n"][0]


class TestFilters:
    def test_week_filter(self, repo):
        assert set(repo.get_txn_hdr(weeks=[5, 6])["week"]) == {5, 6}

    def test_txn_itm_week_filter_joins_through_lookup_day(self, repo, q):
        n = q("""SELECT COUNT(*) AS n FROM txn_itm i JOIN lookup_day d ON d.day = i.day
                 WHERE d.week = 7""")["n"][0]
        assert len(repo.get_txn_itm(weeks=[7])) == n

    def test_filters_combine_with_and(self, repo):
        df = repo.get_txn_hdr(weeks=[5], store_ids=[1, 2])
        assert set(df["week"]) == {5} and set(df["store_id"]) <= {1, 2}

    def test_dimension_filters(self, repo):
        assert set(repo.get_stores(["West"])["region"]) == {"West"}
        assert set(repo.get_upcs(["Beverages"])["department"]) == {"Beverages"}
        assert set(repo.get_household_segmentation(["Young Singles"])["segment_name"]) == {"Young Singles"}

    def test_an_empty_filter_matches_nothing_instead_of_everything(self, repo):
        assert repo.get_txn_hdr(weeks=[]).empty
        assert repo.get_stores(regions=[]).empty

    def test_filter_values_are_bound_parameters_not_sql(self, repo):
        assert repo.get_stores(["West'; DROP TABLE store;--"]).empty
        assert len(repo.get_stores()) == 24


class TestErrorHandling:
    def test_missing_database_file(self, tmp_path):
        with pytest.raises(DataSourceUnavailableError, match="generate_synthetic_data"):
            SQLiteDataSource(tmp_path / "nope.db").ping()

    def test_bad_sql_becomes_a_query_error(self, db_path):
        with pytest.raises(QueryError):
            SQLiteDataSource(db_path).read("SELECT * FROM no_such_table")

    def test_connections_are_read_only(self, db_path):
        with pytest.raises(QueryError):
            SQLiteDataSource(db_path).read("DELETE FROM store")

    def test_unsupported_backend(self):
        with pytest.raises(UnsupportedDataSourceError, match="postgres"):
            create_data_source("postgres://user:pw@host/db")

    def test_all_failures_share_one_base_class(self):
        for exc in (DataSourceUnavailableError, QueryError, UnsupportedDataSourceError):
            assert issubclass(exc, DataAccessError)

    def test_unsupported_error_does_not_leak_the_url_password(self):
        with pytest.raises(UnsupportedDataSourceError) as info:
            create_data_source("postgres://svc:SuperSecret@host/db")
        assert "SuperSecret" not in str(info.value)
