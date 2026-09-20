"""Typed query functions, one per table, on top of any `DataSource`.

Every method returns a DataFrame whose columns are exactly the table's columns. Optional
filters narrow the result; a filter given as an empty sequence matches nothing (rather than
being ignored), so a caller can never accidentally widen a query.

`txn_itm` has no `week` column, so week filters join `lookup_day` on `day`.

These functions return row-level data and are for the analysis layer only, inside the company
boundary. Nothing row-level may be passed on to the narrative layer (see the data-boundary rule).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import pandas as pd

from src.data.source import DataSource

TXN_HDR_COLUMNS = ("basket_id", "household_id", "store_id", "day", "week", "trans_time",
                   "total_basket_value")  # fmt: skip
TXN_ITM_COLUMNS = ("basket_id", "household_id", "store_id", "day", "upc", "quantity",
                   "sales_value", "retail_discount", "coupon_discount", "promo_flag")  # fmt: skip
UPC_COLUMNS = ("upc", "department", "commodity", "brand", "base_price")
STORE_COLUMNS = ("store_id", "region", "store_format", "size_sqft")
LOOKUP_DAY_COLUMNS = ("day", "week", "calendar_date", "holiday_flag", "season")
HOUSEHOLD_COLUMNS = ("household_id", "segment_name", "income_band", "family_size")
PROMO_COLUMNS = ("upc", "store_id", "week", "promo_type", "discount_pct")


def _in_filter(column: str, values: Iterable[Any] | None, name: str, params: dict[str, Any]) -> str | None:
    """Build an `IN` clause with bound parameters. `column` is always a hardcoded literal."""
    if values is None:
        return None
    items = list(values)
    if not items:
        return "1 = 0"
    keys = []
    for i, value in enumerate(items):
        key = f"{name}_{i}"
        params[key] = value
        keys.append(f":{key}")
    return f"{column} IN ({', '.join(keys)})"


def _where(clauses: Sequence[str | None]) -> str:
    active = [c for c in clauses if c]
    return f" WHERE {' AND '.join(active)}" if active else ""


def _cols(columns: Sequence[str], alias: str) -> str:
    return ", ".join(f"{alias}.{c}" for c in columns)


class RetailRepository:
    """Read access to the Retail Pulse tables. Depends only on the `DataSource` interface."""

    def __init__(self, source: DataSource) -> None:
        self._source = source

    def ping(self) -> None:
        self._source.ping()

    # ---- fact tables ----------------------------------------------------------------
    def get_txn_hdr(self, weeks: Sequence[int] | None = None,
                    store_ids: Sequence[int] | None = None) -> pd.DataFrame:  # fmt: skip
        """Basket-level transactions, optionally limited to weeks and/or stores."""
        params: dict[str, Any] = {}
        where = _where([_in_filter("h.week", weeks, "week", params),
                        _in_filter("h.store_id", store_ids, "store", params)])  # fmt: skip
        return self._source.read(f"SELECT {_cols(TXN_HDR_COLUMNS, 'h')} FROM txn_hdr h{where}", params)

    def get_txn_itm(self, weeks: Sequence[int] | None = None,
                    store_ids: Sequence[int] | None = None,
                    upcs: Sequence[int] | None = None) -> pd.DataFrame:  # fmt: skip
        """UPC-level transaction lines, optionally limited to weeks, stores and/or UPCs."""
        params: dict[str, Any] = {}
        where = _where([_in_filter("d.week", weeks, "week", params),
                        _in_filter("i.store_id", store_ids, "store", params),
                        _in_filter("i.upc", upcs, "upc", params)])  # fmt: skip
        sql = (f"SELECT {_cols(TXN_ITM_COLUMNS, 'i')} FROM txn_itm i "
               f"JOIN lookup_day d ON d.day = i.day{where}")  # fmt: skip
        return self._source.read(sql, params)

    def get_promos(self, weeks: Sequence[int] | None = None,
                   store_ids: Sequence[int] | None = None,
                   upcs: Sequence[int] | None = None) -> pd.DataFrame:  # fmt: skip
        """Promotions by UPC, store and week."""
        params: dict[str, Any] = {}
        where = _where([_in_filter("p.week", weeks, "week", params),
                        _in_filter("p.store_id", store_ids, "store", params),
                        _in_filter("p.upc", upcs, "upc", params)])  # fmt: skip
        return self._source.read(f"SELECT {_cols(PROMO_COLUMNS, 'p')} FROM promo p{where}", params)

    # ---- dimension tables -----------------------------------------------------------
    def get_upcs(self, departments: Sequence[str] | None = None) -> pd.DataFrame:
        params: dict[str, Any] = {}
        where = _where([_in_filter("u.department", departments, "dept", params)])
        return self._source.read(f"SELECT {_cols(UPC_COLUMNS, 'u')} FROM upc u{where}", params)

    def get_stores(self, regions: Sequence[str] | None = None) -> pd.DataFrame:
        params: dict[str, Any] = {}
        where = _where([_in_filter("s.region", regions, "region", params)])
        return self._source.read(f"SELECT {_cols(STORE_COLUMNS, 's')} FROM store s{where}", params)

    def get_lookup_days(self, weeks: Sequence[int] | None = None) -> pd.DataFrame:
        params: dict[str, Any] = {}
        where = _where([_in_filter("d.week", weeks, "week", params)])
        return self._source.read(
            f"SELECT {_cols(LOOKUP_DAY_COLUMNS, 'd')} FROM lookup_day d{where}", params)  # fmt: skip

    def get_household_segmentation(self, segments: Sequence[str] | None = None) -> pd.DataFrame:
        params: dict[str, Any] = {}
        where = _where([_in_filter("g.segment_name", segments, "segment", params)])
        return self._source.read(
            f"SELECT {_cols(HOUSEHOLD_COLUMNS, 'g')} FROM household_segmentation g{where}", params)  # fmt: skip
