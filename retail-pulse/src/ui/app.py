"""Retail Pulse - Streamlit front end.

Run from the project root:  streamlit run src/ui/app.py

Presentation only. This module calls `src.analysis` and `src.narrative` and formats what they
return; it holds no business logic and never touches the data layer or any model directly.
The analyst report is generated on demand (button), not on every widget change, because each
report is a paid API call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # lets `streamlit run src/ui/app.py` find the packages
    sys.path.insert(0, str(_ROOT))

from config.settings import get_settings  # noqa: E402
from src.analysis import (  # noqa: E402
    AnalysisError,
    WeeklyAnalysis,
    analyze_week,
    as_dict,
    available_regions,
    available_weeks,
)
from src.narrative import (  # noqa: E402
    NarrativeConfigError,
    NarrativeGenerationError,
    NarrativeGenerator,
    RawDataBoundaryError,
    describe_provider,
    to_payload,
)

ALL_REGIONS = "All regions"


# ---------------------------------------------------------------------------- cached calls
@st.cache_data(show_spinner=False)
def _options() -> tuple[list[int], list[str]]:
    return available_weeks(), available_regions()


@st.cache_data(show_spinner="Crunching the numbers...")
def _analysis(week: int, region: str | None) -> WeeklyAnalysis:
    return analyze_week(week, region)


# ---------------------------------------------------------------------------- formatting
def _pct(value: float | None, digits: int = 1) -> str | None:
    return None if value is None else f"{value:+.{digits}f}%"


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.0f}"


def _table(rows: list[dict], columns: dict[str, str]) -> pd.DataFrame:
    """Rows -> display table with friendly column names (presentation only)."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df[list(columns)].rename(columns=columns)


# ---------------------------------------------------------------------------- sections
def _metric_cards(a: WeeklyAnalysis) -> None:
    sales, stock, promo, segs = a.sales, a.stockouts, a.promo, a.segments
    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total sales", _money(sales.total_sales), _pct(sales.total_change_pct),
              help="Net item sales (after promo discounts, before coupons) vs the prior week.")  # fmt: skip

    if stock.has_history:
        c2.metric("Suspected stockouts", f"{stock.n_skus_affected} SKUs",
                  f"{_money(stock.est_sales_at_risk)} weekly sales at risk", delta_color="off",
                  help="SKUs that normally sell steadily but sold zero. "
                       "Inferred from sales, not inventory.")  # fmt: skip
    else:
        c2.metric("Suspected stockouts", "n/a", "not enough history", delta_color="off")

    if promo.has_promos:
        c3.metric("Promo unit lift", _pct(promo.unit_lift_pct, 0) or "n/a",
                  f"{promo.n_promoted_items} promoted items", delta_color="off",
                  help="Promoted units vs each item's own non-promo weekly average.")  # fmt: skip
    else:
        c3.metric("Promo unit lift", "No promos", "none this week", delta_color="off")

    if segs.segments:
        top = segs.segments[0]
        c4.metric("Top segment", top.segment_name,
                  f"{top.share_of_sales_pct}% of sales" if top.share_of_sales_pct is not None else None,
                  delta_color="off", help="Household segment with the largest share of sales.")  # fmt: skip
    else:
        c4.metric("Top segment", "n/a")


def _details(a: WeeklyAnalysis) -> None:
    with st.expander("Details behind the cards", expanded=False):
        sales = as_dict(a.sales)
        st.markdown("**Biggest sales movers (department x region)**")
        st.dataframe(
            _table(sales["top_movers"], {"department": "Department", "region": "Region", "sales": "Sales",
                                         "prior_sales": "Prior week", "change_pct": "Change %"}),
            hide_index=True, use_container_width=True)  # fmt: skip

        if a.stockouts.n_store_sku_pairs:
            st.markdown("**Suspected stockouts (top SKUs)**")
            stock = as_dict(a.stockouts)
            st.dataframe(
                _table(stock["top_skus"], {"upc": "UPC", "department": "Department", "commodity": "Commodity",
                                           "brand": "Brand", "n_stores_affected": "Stores hit",
                                           "est_sales_at_risk": "Sales at risk"}),
                hide_index=True, use_container_width=True)  # fmt: skip

        if a.promo.has_promos:
            st.markdown("**Promo lift by promo type**")
            promo = as_dict(a.promo)
            st.dataframe(
                _table(promo["by_promo_type"], {"promo_type": "Type", "n_items": "Items",
                                                "unit_lift_pct": "Unit lift %", "sales_lift_pct": "Sales lift %"}),
                hide_index=True, use_container_width=True)  # fmt: skip

        st.markdown("**Segment basket behavior**")
        segs = as_dict(a.segments)
        st.dataframe(
            _table(segs["segments"], {"segment_name": "Segment", "n_baskets": "Baskets",
                                      "avg_basket_value": "Avg basket", "basket_value_change_pct": "Basket change %",
                                      "avg_items_per_basket": "Items/basket", "promo_item_share_pct": "Promo item %"}),
            hide_index=True, use_container_width=True)  # fmt: skip


def _narrative_section(a: WeeklyAnalysis) -> None:
    st.subheader("Analyst report")
    key = (a.week, a.region)
    engine = describe_provider(get_settings())
    st.caption(f"Report engine: {engine}")

    if st.button("Generate analyst report", type="primary",
                 help="Only the aggregated figures above are used, never raw records."):  # fmt: skip
        try:
            with st.spinner("Writing the report (the first run loads the model and can take a minute)..."):
                st.session_state["report"] = (key, NarrativeGenerator().generate(a.summaries()))
        except NarrativeConfigError as exc:
            st.warning(f"The report engine is not ready. {exc}")
        except RawDataBoundaryError as exc:
            st.error(f"Blocked by the data-boundary guard: {exc}")
        except NarrativeGenerationError as exc:
            st.error(f"Could not generate the report: {exc}")

    saved = st.session_state.get("report")
    if saved and saved[0] == key:  # only show a report that matches the current selection
        report = saved[1]
        st.success(report.headline)
        st.markdown(f"**Likely cause**  \n{report.likely_cause}")
        st.markdown("**Recommended actions**")
        for i, action in enumerate(report.recommended_actions, start=1):
            st.markdown(f"{i}. {action}")

    with st.expander("What gets sent to the report engine (aggregated figures only)"):
        try:
            st.json(json.loads(json.dumps(to_payload(a.summaries()))), expanded=False)
        except RawDataBoundaryError as exc:
            st.error(str(exc))


# ---------------------------------------------------------------------------- page
def main() -> None:
    st.set_page_config(page_title="Retail Pulse", page_icon=":bar_chart:", layout="wide")
    st.title("Retail Pulse")
    st.caption("Weekly retail performance, explained in plain English.")

    settings = get_settings()
    try:
        weeks, regions = _options()
    except AnalysisError as exc:
        st.error(f"Data source unavailable: {exc}")
        st.stop()

    with st.sidebar:
        st.header("Report settings")
        week = st.selectbox("Week", weeks, index=len(weeks) - 1, format_func=lambda w: f"Week {w}")
        region_choice = st.selectbox("Region", [ALL_REGIONS, *regions])
        st.divider()
        st.caption(f"Environment: **{settings.env.value}**"
                   + (" (synthetic data)" if settings.is_dev else ""))  # fmt: skip

    region = None if region_choice == ALL_REGIONS else region_choice
    try:
        analysis = _analysis(week, region)
    except AnalysisError as exc:
        st.error(f"Could not analyse week {week}: {exc}")
        st.stop()

    st.subheader(f"Week {week} - {region_choice}")
    _metric_cards(analysis)
    _details(analysis)
    st.divider()
    _narrative_section(analysis)


main()
