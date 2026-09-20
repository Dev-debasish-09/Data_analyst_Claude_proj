"""Shared fixtures.

The suite builds its OWN synthetic database in a temp directory (seeded, so identical every run).
It never touches `local_dev.db` and never needs a network or an API key.
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from src.data import RetailRepository, SQLiteDataSource

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SEED = 42


@dataclass(frozen=True)
class PlantedAnomalies:
    """The answer key written by the generator (`dev_ground_truth`)."""

    stockout_region: str
    stockout_start_week: int
    stockout_end_week: int
    stockout_pairs: frozenset  # {(store_id, upc), ...}
    stockout_upcs: frozenset
    no_promo_week: int


@pytest.fixture(scope="session")
def db_path(tmp_path_factory) -> Path:
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import generate_synthetic_data as generator
    finally:
        sys.path.remove(str(SCRIPTS_DIR))
    path = tmp_path_factory.mktemp("synthetic") / "test.db"
    generator.generate_database(path, seed=SEED)
    return path


@pytest.fixture(scope="session")
def repo(db_path) -> RetailRepository:
    return RetailRepository(SQLiteDataSource(db_path))


@pytest.fixture(scope="session")
def q(db_path):
    """Run raw SQL straight against the database, independent of the data layer under test."""

    def run(sql: str, **params) -> pd.DataFrame:
        with closing(sqlite3.connect(db_path)) as conn:
            return pd.read_sql_query(sql, conn, params=params)

    return run


@pytest.fixture(scope="session")
def planted(q) -> PlantedAnomalies:
    truth = q("SELECT * FROM dev_ground_truth")
    stock = truth[truth["anomaly_type"] == "regional_stockout"]
    no_promo = truth[truth["anomaly_type"] == "no_promo_week"]
    return PlantedAnomalies(
        stockout_region=stock["region"].iloc[0],
        stockout_start_week=int(stock["start_week"].iloc[0]),
        stockout_end_week=int(stock["end_week"].iloc[0]),
        stockout_pairs=frozenset(zip(stock["store_id"], stock["upc"])),
        stockout_upcs=frozenset(int(u) for u in stock["upc"]),
        no_promo_week=int(no_promo["start_week"].iloc[0]),
    )
