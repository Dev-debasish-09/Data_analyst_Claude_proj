"""Structured summary objects returned by the analysis layer.

These are the ONLY things the narrative layer may receive. They hold pre-aggregated figures
(totals, percentages, top-N lists) and never row-level records or household identifiers.

Conventions
  * `*_pct` values are percentages rounded to 1 decimal (12.3 means +12.3%), or None when the
    comparison is undefined (e.g. no prior week, zero baseline).
  * Money is in the currency of `sales_value`, rounded to 2 decimals.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SalesDelta:
    department: str | None
    region: str | None
    sales: float
    prior_sales: float | None
    change_amount: float | None
    change_pct: float | None


@dataclass(frozen=True)
class WeeklySalesChangeSummary:
    week: int
    prior_week: int | None
    region_filter: str | None
    has_prior_data: bool
    total_sales: float
    prior_total_sales: float | None
    total_change_pct: float | None
    by_department: tuple[SalesDelta, ...]
    by_region: tuple[SalesDelta, ...]
    top_movers: tuple[SalesDelta, ...]  # department x region, largest absolute $ change


@dataclass(frozen=True)
class RegionStockout:
    region: str
    n_stores: int
    n_skus: int
    est_sales_at_risk: float


@dataclass(frozen=True)
class StockoutSku:
    upc: int
    department: str
    commodity: str
    brand: str
    n_stores_affected: int
    est_sales_at_risk: float


@dataclass(frozen=True)
class StockoutSummary:
    week: int
    region_filter: str | None
    has_history: bool
    history_weeks_used: int
    n_store_sku_pairs: int
    n_stores_affected: int
    n_skus_affected: int
    est_sales_at_risk: float
    by_region: tuple[RegionStockout, ...]
    top_skus: tuple[StockoutSku, ...]


@dataclass(frozen=True)
class PromoTypeLift:
    promo_type: str
    n_items: int
    unit_lift_pct: float | None
    sales_lift_pct: float | None


@dataclass(frozen=True)
class PromoLiftSummary:
    week: int
    region_filter: str | None
    has_promos: bool
    n_promoted_items: int  # promoted store-UPC combinations in the week
    n_items_with_baseline: int  # of those, how many had enough non-promo history to compare
    avg_discount_pct: float | None
    promo_units: float
    baseline_units: float
    unit_lift_pct: float | None
    promo_sales: float
    baseline_sales: float
    sales_lift_pct: float | None
    by_promo_type: tuple[PromoTypeLift, ...]


@dataclass(frozen=True)
class SegmentBehavior:
    segment_name: str
    n_baskets: int
    n_households: int
    total_sales: float
    share_of_sales_pct: float | None
    avg_basket_value: float | None
    prior_avg_basket_value: float | None
    basket_value_change_pct: float | None
    avg_items_per_basket: float | None
    promo_item_share_pct: float | None


@dataclass(frozen=True)
class SegmentBehaviorSummary:
    week: int
    prior_week: int | None
    region_filter: str | None
    segments: tuple[SegmentBehavior, ...]


def as_dict(summary: Any) -> dict[str, Any]:
    """Plain-dict form of any summary (nested dataclasses included), e.g. for the narrative layer."""
    return asdict(summary)
