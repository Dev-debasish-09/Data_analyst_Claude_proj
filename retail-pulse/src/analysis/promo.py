"""Promo lift: promoted vs non-promoted sales for the same store-SKU."""

from __future__ import annotations

import pandas as pd

from src.analysis.common import load_items, money, pct_change, resolve_stores, validate_week
from src.analysis.models import PromoLiftSummary, PromoTypeLift
from src.data import RetailRepository

DEFAULT_LOOKBACK_WEEKS = 8
MIN_BASELINE_WEEKS = 3


def promo_lift(
    repo: RetailRepository,
    week: int,
    region: str | None = None,
    lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS,
) -> PromoLiftSummary:
    """Measure how much promoted items outsold their own normal (non-promo) rate this week.

    Business logic
      * Each promoted store-SKU is compared with ITSELF: its baseline is the average weekly
        units (and sales) across the previous `lookback_weeks` weeks in which it was NOT on
        promotion in that store. Weeks with no sales count as zero. Comparing an item with
        itself removes the difference between popular and unpopular products.
      * A store-SKU needs at least MIN_BASELINE_WEEKS non-promo weeks in the lookback to be
        evaluated; otherwise its baseline is too noisy and it is excluded (see
        `n_items_with_baseline`).
      * Lift is aggregated as total promo-week volume over total baseline volume, minus 1. This
        is volume-weighted, so a few slow items with wild ratios cannot dominate.
      * `unit_lift_pct` measures demand response. `sales_lift_pct` is lower because
        `sales_value` is net of the promo discount: a 3x unit lift at 25% off is about 2.3x
        revenue. Both are reported because merchandising cares about volume and finance about
        revenue. Neither is incremental profit, and neither adjusts for cannibalisation or
        post-promo dips.
      * A week with no promotions (`has_promos` False) returns zeros and None lifts.
    """
    all_weeks = validate_week(repo, week)
    stores = resolve_stores(repo, region)
    store_ids = stores["store_id"].tolist() if region else None

    promos = repo.get_promos(weeks=[week], store_ids=store_ids)
    if promos.empty:
        return PromoLiftSummary(week, region, False, 0, 0, None, 0.0, 0.0, None, 0.0, 0.0, None, ())

    history = [w for w in range(week - lookback_weeks, week) if w in all_weeks]
    pairs = promos[["store_id", "upc", "promo_type", "discount_pct"]]
    upcs = pairs["upc"].unique().tolist()

    items = load_items(repo, history + [week], stores, region, upcs=upcs)
    weekly = items.groupby(["store_id", "upc", "week"], as_index=False).agg(
        units=("quantity", "sum"), sales=("sales_value", "sum")
    )

    # Baseline: full pair x history-week grid (missing = zero sales), minus weeks on promo.
    grid = pairs[["store_id", "upc"]].merge(pd.DataFrame({"week": pd.Series(history, dtype="int64")}), how="cross")
    grid = grid.merge(weekly, on=["store_id", "upc", "week"], how="left").fillna({"units": 0, "sales": 0})
    hist_promos = repo.get_promos(weeks=history, store_ids=store_ids, upcs=upcs)[["store_id", "upc", "week"]]
    grid = grid.merge(hist_promos.assign(on_promo=True), on=["store_id", "upc", "week"], how="left")
    grid = grid[grid["on_promo"].isna()]
    base = grid.groupby(["store_id", "upc"]).agg(
        base_units=("units", "mean"), base_sales=("sales", "mean"), n_weeks=("week", "nunique")
    ).reset_index()
    base = base[base["n_weeks"] >= MIN_BASELINE_WEEKS]

    current = weekly[weekly["week"] == week][["store_id", "upc", "units", "sales"]]
    detail = pairs.merge(base, on=["store_id", "upc"]).merge(current, on=["store_id", "upc"], how="left")
    detail = detail.fillna({"units": 0, "sales": 0})

    def totals(df: pd.DataFrame) -> tuple[float, float, float, float]:
        return (df["units"].sum(), df["base_units"].sum(), df["sales"].sum(), df["base_sales"].sum())

    pu, bu, ps, bs = totals(detail)
    by_type = []
    for ptype, g in detail.groupby("promo_type"):
        gpu, gbu, gps, gbs = totals(g)
        by_type.append(PromoTypeLift(ptype, len(g), pct_change(gpu, gbu), pct_change(gps, gbs)))

    return PromoLiftSummary(
        week=week,
        region_filter=region,
        has_promos=True,
        n_promoted_items=len(pairs),
        n_items_with_baseline=len(detail),
        avg_discount_pct=round(float(pairs["discount_pct"].mean()) * 100, 1),
        promo_units=round(float(pu), 1),
        baseline_units=round(float(bu), 1),
        unit_lift_pct=pct_change(pu, bu),
        promo_sales=money(ps),
        baseline_sales=money(bs),
        sales_lift_pct=pct_change(ps, bs),
        by_promo_type=tuple(sorted(by_type, key=lambda t: t.promo_type)),
    )
