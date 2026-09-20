"""Shared helpers for the analysis functions."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from src.data import RetailRepository


class AnalysisError(ValueError):
    """Invalid analysis input (unknown week or region)."""


def pct_change(current: float, prior: float | None) -> float | None:
    """Percent change vs `prior`, or None when it is undefined (missing or zero prior)."""
    if prior is None or prior == 0:
        return None
    return round((current - prior) / prior * 100, 1)


def money(value: float) -> float:
    return round(float(value), 2)


def validate_week(repo: RetailRepository, week: int) -> list[int]:
    """Return all weeks in the data; raise if `week` is not one of them."""
    weeks = sorted(int(w) for w in repo.get_lookup_days()["week"].unique())
    if week not in weeks:
        raise AnalysisError(f"Unknown week {week}; data covers weeks {weeks[0]}-{weeks[-1]}.")
    return weeks


def resolve_stores(repo: RetailRepository, region: str | None) -> pd.DataFrame:
    """Store dimension, restricted to `region` when given."""
    stores = repo.get_stores([region] if region else None)
    if stores.empty:
        known = sorted(repo.get_stores()["region"].unique())
        raise AnalysisError(f"Unknown region {region!r}; known regions: {known}.")
    return stores


def load_items(
    repo: RetailRepository,
    weeks: Sequence[int],
    stores: pd.DataFrame,
    region: str | None,
    upcs: Sequence[int] | None = None,
) -> pd.DataFrame:
    """Line items for `weeks` with a `week` column added (txn_itm only carries `day`)."""
    store_ids = stores["store_id"].tolist() if region else None
    items = repo.get_txn_itm(weeks=list(weeks), store_ids=store_ids, upcs=upcs)
    days = repo.get_lookup_days(list(weeks))[["day", "week"]]
    return items.merge(days, on="day", how="inner")
