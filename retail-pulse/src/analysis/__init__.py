"""Analysis layer: turns repository data into small, pre-aggregated summary objects."""

from src.analysis.common import AnalysisError
from src.analysis.models import (
    PromoLiftSummary,
    SegmentBehaviorSummary,
    StockoutSummary,
    WeeklySalesChangeSummary,
    as_dict,
)
from src.analysis.promo import promo_lift
from src.analysis.sales import weekly_sales_change
from src.analysis.segments import segment_basket_behavior
from src.analysis.service import WeeklyAnalysis, analyze_week, available_regions, available_weeks
from src.analysis.stockouts import detect_stockouts

__all__ = [
    "AnalysisError",
    "PromoLiftSummary",
    "SegmentBehaviorSummary",
    "StockoutSummary",
    "WeeklyAnalysis",
    "WeeklySalesChangeSummary",
    "analyze_week",
    "as_dict",
    "available_regions",
    "available_weeks",
    "detect_stockouts",
    "promo_lift",
    "segment_basket_behavior",
    "weekly_sales_change",
]
