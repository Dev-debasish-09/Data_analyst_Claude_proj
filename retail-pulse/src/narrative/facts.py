"""Turns the (already guarded) aggregate payload into a short plain-text fact sheet.

Small local models follow a few clear sentences far more reliably than a nested JSON blob, and
are much less likely to invent numbers when every figure they need is stated in words. This only
re-formats figures that are already in the payload; it computes nothing new and never sees
anything the guard has not already approved.
"""

from __future__ import annotations

from typing import Any


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.0f}"


def _pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}%"


def _sales_facts(s: dict[str, Any]) -> list[str]:
    scope = s["region_filter"] or "All regions"
    line = f"Total sales in week {s['week']} for {scope}: {_money(s['total_sales'])}"
    if s["has_prior_data"] and s["total_change_pct"] is not None:
        line += f", {_pct(s['total_change_pct'])} versus week {s['prior_week']} ({_money(s['prior_total_sales'])})."
    else:
        line += ". There is no prior week to compare with."
    lines = [line]
    movers = [m for m in s["top_movers"] if m["change_pct"] is not None][:3]
    for m in movers:
        name = " in ".join(x for x in (m["department"], m["region"]) if x)
        lines.append(f"- Biggest mover: {name}, {_money(m['sales'])} ({_pct(m['change_pct'])}, "
                     f"{m['change_amount']:+,.0f} dollars).")  # fmt: skip
    return lines


def _stockout_facts(s: dict[str, Any]) -> list[str]:
    if not s["has_history"]:
        return ["Stockout check: not enough sales history this early in the data."]
    if not s["n_skus_affected"]:
        return ["Stockout check: no suspected stockouts this week."]
    regions = ", ".join(r["region"] for r in s["by_region"])
    lines = [f"Suspected stockouts (inferred from zero sales, not measured inventory): {s['n_skus_affected']} products "
             f"in {s['n_stores_affected']} stores in {regions}, about {_money(s['est_sales_at_risk'])} of weekly "
             f"sales at risk."]  # fmt: skip
    for k in s["top_skus"][:3]:
        lines.append(f"- {k['department']} / {k['commodity']} ({k['brand']}): zero sales in "
                     f"{k['n_stores_affected']} stores, about {_money(k['est_sales_at_risk'])} at risk.")  # fmt: skip
    return lines


def _promo_facts(p: dict[str, Any]) -> list[str]:
    if not p["has_promos"]:
        return ["Promotions: none this week."]
    line = f"Promotions: {p['n_promoted_items']} promoted items"
    if p["avg_discount_pct"] is not None:
        line += f" at an average {p['avg_discount_pct']:.0f}% discount"
    if p["unit_lift_pct"] is not None:
        line += (f"; they sold {_pct(p['unit_lift_pct'], 0)} more units than the same items normally do "
                 f"and {_pct(p['sales_lift_pct'], 0)} more sales value.")  # fmt: skip
    else:
        line += "; there is not enough history to measure their lift."
    return [line]


def _segment_facts(s: dict[str, Any]) -> list[str]:
    lines = []
    for seg in s["segments"][:4]:
        lines.append(f"- {seg['segment_name']}: {seg['share_of_sales_pct']}% of sales, average basket "
                     f"{_money(seg['avg_basket_value'])} ({_pct(seg['basket_value_change_pct'])} versus last week), "
                     f"{seg['promo_item_share_pct']}% of items bought on promotion.")  # fmt: skip
    return ["Household segments:", *lines] if lines else []


def build_facts(payload: dict[str, Any]) -> str:
    """Plain-text fact sheet for the payload (any subset of the four summaries)."""
    lines: list[str] = []
    stock = payload.get("StockoutSummary")
    if stock and stock["n_skus_affected"]:  # the most actionable finding goes first
        lines += ["MOST IMPORTANT FINDING:", *_stockout_facts(stock), ""]
    if "WeeklySalesChangeSummary" in payload:
        lines += _sales_facts(payload["WeeklySalesChangeSummary"])
    if stock and not stock["n_skus_affected"]:
        lines += _stockout_facts(stock)
    if "PromoLiftSummary" in payload:
        lines += _promo_facts(payload["PromoLiftSummary"])
    if "SegmentBehaviorSummary" in payload:
        lines += _segment_facts(payload["SegmentBehaviorSummary"])
    return "\n".join(lines)
