"""Segment-level basket behavior."""

from __future__ import annotations

from src.analysis.common import load_items, money, pct_change, resolve_stores, validate_week
from src.analysis.models import SegmentBehavior, SegmentBehaviorSummary
from src.data import RetailRepository


def segment_basket_behavior(
    repo: RetailRepository, week: int, region: str | None = None
) -> SegmentBehaviorSummary:
    """Summarise how each household segment shopped this week, versus the week before.

    Business logic
      * A basket is one checkout (`txn_hdr` row); its value is `total_basket_value`, which is net
        of both promo discounts and coupons: what the household actually paid.
      * `avg_basket_value` is that total divided by basket count. `basket_value_change_pct`
        compares it with the prior week (None in the first week or if the segment did not shop).
      * `avg_items_per_basket` counts distinct line items (UPC lines), not units.
      * `promo_item_share_pct` is the share of line items bought on promotion. A rising share
        with a falling basket value suggests promo-driven trading down; a segment with a high
        share is promo-sensitive.
      * `share_of_sales_pct` is the segment's share of total basket value in the week.
      * `n_households` is the count of distinct households that shopped (a count only; identifiers
        never leave this function).
    """
    all_weeks = validate_week(repo, week)
    stores = resolve_stores(repo, region)
    store_ids = stores["store_id"].tolist() if region else None
    prior = week - 1 if (week - 1) in all_weeks else None
    weeks = [week] + ([prior] if prior else [])

    segments = repo.get_household_segmentation()[["household_id", "segment_name"]]
    hdr = repo.get_txn_hdr(weeks=weeks, store_ids=store_ids).merge(segments, on="household_id")
    items = load_items(repo, [week], stores, region).merge(segments, on="household_id")

    cur = hdr[hdr["week"] == week]
    prev = hdr[hdr["week"] == prior] if prior else hdr.iloc[0:0]
    prior_avg = prev.groupby("segment_name")["total_basket_value"].mean()
    total_sales = float(cur["total_basket_value"].sum())
    lines_per_segment = items.groupby("segment_name").agg(
        lines=("upc", "size"), promo_lines=("promo_flag", "sum")
    )

    rows = []
    for name, g in cur.groupby("segment_name"):
        n = len(g)
        seg_total = float(g["total_basket_value"].sum())
        avg = seg_total / n
        prior_val = float(prior_avg[name]) if name in prior_avg.index else None
        lines = lines_per_segment.loc[name] if name in lines_per_segment.index else None
        rows.append(SegmentBehavior(
            segment_name=name,
            n_baskets=n,
            n_households=int(g["household_id"].nunique()),
            total_sales=money(seg_total),
            share_of_sales_pct=round(seg_total / total_sales * 100, 1) if total_sales else None,
            avg_basket_value=money(avg),
            prior_avg_basket_value=None if prior_val is None else money(prior_val),
            basket_value_change_pct=pct_change(avg, prior_val),
            avg_items_per_basket=None if lines is None else round(float(lines["lines"]) / n, 1),
            promo_item_share_pct=None if lines is None
            else round(float(lines["promo_lines"]) / float(lines["lines"]) * 100, 1),
        ))  # fmt: skip
    rows.sort(key=lambda s: -s.total_sales)
    return SegmentBehaviorSummary(week, prior, region, tuple(rows))
