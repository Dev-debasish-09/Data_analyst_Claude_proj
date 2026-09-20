"""Stockout detection: SKUs with sales history that drop to zero in a store."""

from __future__ import annotations

import pandas as pd

from src.analysis.common import load_items, money, resolve_stores, validate_week
from src.analysis.models import RegionStockout, StockoutSku, StockoutSummary
from src.data import RetailRepository

DEFAULT_LOOKBACK_WEEKS = 8
MIN_HISTORY_WEEKS = 3
DEFAULT_MIN_BASELINE_UNITS = 15.0


def detect_stockouts(
    repo: RetailRepository,
    week: int,
    region: str | None = None,
    lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS,
    min_baseline_units: float = DEFAULT_MIN_BASELINE_UNITS,
    top_n: int = 5,
) -> StockoutSummary:
    """Flag store-SKU pairs that normally sell but recorded zero units this week.

    Business logic
      * We only see sales, not inventory, so a stockout is inferred: a SKU that sells steadily
        and suddenly sells nothing is presumed to be out of stock.
      * "Steadily" is judged on the MEDIAN weekly units over the previous `lookback_weeks` weeks
        (weeks with no sales count as zero). The median, not the mean, so a stockout already
        under way (whose zero weeks would drag a mean down) does not hide itself. Weeks in which
        the SKU was sold on promotion (in that store, or anywhere in the region for the region
        tier) are excluded from the baseline, because promo volume is not "normal" volume.
      * Slow sellers hit zero by chance, and there are thousands of store-SKU pairs, so a zero is
        only treated as a stockout when it is statistically implausible. Two tiers:
          1. STORE tier: a store's own baseline is at least `min_baseline_units` (default 15)
             and it sold zero. At 15 units a week, a chance zero is under 0.0001%. Tuned on the synthetic data: 15 gave no false alarms
             in 45 normal weeks, 10 gave 5 alarm weeks; the cost is missing the slowest planted SKUs.
          2. REGION tier: the SKU sold zero across ALL stores in a region while the region's
             combined baseline is at least `min_baseline_units`. Individually each store may
             sell too little to be conclusive, but zero everywhere at once is strong evidence
             (a regional supply failure). The region's stores that used to sell the SKU
             (median >= 1 unit a week) are flagged.
      * `est_sales_at_risk` is the median weekly sales value of the flagged pairs: what would
        normally have been sold this week. It estimates revenue exposure, not measured loss.
      * With fewer than MIN_HISTORY_WEEKS prior weeks (weeks 1-3) there is no baseline, so
        `has_history` is False and nothing is flagged.
    """
    all_weeks = validate_week(repo, week)
    stores = resolve_stores(repo, region)
    history = [w for w in range(week - lookback_weeks, week) if w in all_weeks]

    if len(history) < MIN_HISTORY_WEEKS:
        return StockoutSummary(week, region, False, len(history), 0, 0, 0, 0.0, (), ())

    window = history + [week]
    items = load_items(repo, window, stores, region)
    pivot = {}
    for value in ("quantity", "sales_value"):
        pivot[value] = items.pivot_table(
            index=["store_id", "upc"], columns="week", values=value, aggfunc="sum", fill_value=0
        ).reindex(columns=window, fill_value=0)

    units = pivot["quantity"]
    sales = pivot["sales_value"]
    # Weeks in which a store sold the SKU on promotion are left out of its baseline: promo weeks
    # inflate "normal" volume, which would make an ordinary week look like a collapse.
    on_promo = (
        items[items["promo_flag"] == 1]
        .pivot_table(index=["store_id", "upc"], columns="week", values="quantity", aggfunc="sum")
        .reindex(index=units.index, columns=window)
        .fillna(0)
        > 0
    )
    region_of = stores.set_index("store_id")["region"]
    store_regions = units.index.get_level_values("store_id").map(region_of)
    upc_ids = units.index.get_level_values("upc")

    regular = units.where(~on_promo)
    hist_median = regular[history].median(axis=1)
    zero_now = units[week] == 0
    store_tier = (hist_median >= min_baseline_units) & zero_now

    keys = [store_regions, upc_ids]
    region_units = units.groupby(keys).sum()
    region_regular = region_units.where(~on_promo.groupby(keys).any())
    region_hit = (region_regular[history].median(axis=1) >= min_baseline_units) & (region_units[week] == 0)
    region_keys = set(region_hit[region_hit].index)
    in_hit_region = [(r, u) in region_keys for r, u in zip(store_regions, upc_ids)]
    region_tier = pd.Series(in_hit_region, index=units.index) & (hist_median >= 1) & zero_now

    flagged = store_tier | region_tier
    if not flagged.any():
        return StockoutSummary(week, region, True, len(history), 0, 0, 0, 0.0, (), ())

    found = sales.where(~on_promo).loc[flagged, history].median(axis=1).rename("est_sales").reset_index()
    found = found.merge(stores[["store_id", "region"]], on="store_id").merge(
        repo.get_upcs()[["upc", "department", "commodity", "brand"]], on="upc"
    )

    by_region = tuple(
        RegionStockout(
            region=name,
            n_stores=int(g["store_id"].nunique()),
            n_skus=int(g["upc"].nunique()),
            est_sales_at_risk=money(g["est_sales"].sum()),
        )
        for name, g in sorted(found.groupby("region"), key=lambda kv: -kv[1]["est_sales"].sum())
    )
    sku_rows = (
        found.groupby(["upc", "department", "commodity", "brand"])
        .agg(n_stores=("store_id", "nunique"), est=("est_sales", "sum"))
        .reset_index()
        .sort_values("est", ascending=False)
        .head(top_n)
    )
    top_skus = tuple(
        StockoutSku(int(r.upc), r.department, r.commodity, r.brand, int(r.n_stores), money(r.est))
        for r in sku_rows.itertuples()
    )
    return StockoutSummary(
        week=week,
        region_filter=region,
        has_history=True,
        history_weeks_used=len(history),
        n_store_sku_pairs=len(found),
        n_stores_affected=int(found["store_id"].nunique()),
        n_skus_affected=int(found["upc"].nunique()),
        est_sales_at_risk=money(found["est_sales"].sum()),
        by_region=by_region,
        top_skus=top_skus,
    )
