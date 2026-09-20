"""Week-over-week sales change by department and region."""

from __future__ import annotations

import pandas as pd

from src.analysis.common import load_items, money, pct_change, resolve_stores, validate_week
from src.analysis.models import SalesDelta, WeeklySalesChangeSummary
from src.data import RetailRepository


def weekly_sales_change(
    repo: RetailRepository, week: int, region: str | None = None, top_n: int = 5
) -> WeeklySalesChangeSummary:
    """Compare a week's sales with the week before it, by department and by region.

    Business logic
      * "Sales" is the sum of line-item `sales_value`: the amount charged for items after
        shelf/promo discounts but before coupons. Coupons are a checkout-level tender adjustment
        and are excluded so the metric tracks merchandise revenue.
      * The prior week is simply `week - 1`. In the first week of data there is no prior week,
        so `has_prior_data` is False and every change figure is None (not zero: "no data" is not
        "no change").
      * `top_movers` ranks department x region cells by absolute dollar change, because a 40%
        swing on a tiny cell matters less than a 10% swing on a large one. A cell that had sales
        last week and none this week appears with a -100% change; that is how a stockout or
        delisting first surfaces here.
      * `region` restricts the whole analysis to one region; by_region then has a single entry.
    """
    all_weeks = validate_week(repo, week)
    stores = resolve_stores(repo, region)
    prior = week - 1 if (week - 1) in all_weeks else None

    items = load_items(repo, [week] + ([prior] if prior else []), stores, region)
    items = items.merge(repo.get_upcs()[["upc", "department"]], on="upc").merge(
        stores[["store_id", "region"]], on="store_id"
    )

    def deltas(keys: list[str]) -> list[SalesDelta]:
        grouped = items.groupby(keys + ["week"], as_index=False)["sales_value"].sum()
        cur = grouped[grouped["week"] == week].drop(columns="week").rename(columns={"sales_value": "sales"})
        if prior is None:
            merged = cur.assign(prior_sales=float("nan"))
        else:
            pri = grouped[grouped["week"] == prior].drop(columns="week")
            pri = pri.rename(columns={"sales_value": "prior_sales"})
            merged = cur.merge(pri, on=keys, how="outer")
            merged["sales"] = merged["sales"].fillna(0.0)
        out = []
        for row in merged.itertuples(index=False):
            has_prior = prior is not None and pd.notna(row.prior_sales)
            prior_sales = float(row.prior_sales) if has_prior else (0.0 if prior is not None else None)
            out.append(SalesDelta(
                department=getattr(row, "department", None),
                region=getattr(row, "region", None),
                sales=money(row.sales),
                prior_sales=None if prior_sales is None else money(prior_sales),
                change_amount=None if prior_sales is None else money(row.sales - prior_sales),
                change_pct=None if prior_sales is None else pct_change(row.sales, prior_sales),
            ))  # fmt: skip
        return out

    by_department = sorted(deltas(["department"]), key=lambda d: -d.sales)
    by_region = sorted(deltas(["region"]), key=lambda d: -d.sales)
    cells = deltas(["department", "region"])
    if prior is None:
        movers = sorted(cells, key=lambda d: -d.sales)
    else:
        movers = sorted(cells, key=lambda d: -abs(d.change_amount or 0.0))

    total = float(items.loc[items["week"] == week, "sales_value"].sum())
    prior_total = float(items.loc[items["week"] == prior, "sales_value"].sum()) if prior else None
    return WeeklySalesChangeSummary(
        week=week,
        prior_week=prior,
        region_filter=region,
        has_prior_data=prior is not None,
        total_sales=money(total),
        prior_total_sales=None if prior_total is None else money(prior_total),
        total_change_pct=pct_change(total, prior_total),
        by_department=tuple(by_department),
        by_region=tuple(by_region),
        top_movers=tuple(movers[:top_n]),
    )
