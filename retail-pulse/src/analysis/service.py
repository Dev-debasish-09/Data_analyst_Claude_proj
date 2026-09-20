"""Facade the UI calls: everything a front end needs, without touching the data layer.

The UI may only call `src.analysis` and `src.narrative`. Choosing a week or region needs to know
what the data contains, and running the four metrics needs a repository, so both live here.
Data-layer failures are re-raised as `AnalysisError`, so callers handle one exception type.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.analysis.common import AnalysisError
from src.analysis.models import (
    PromoLiftSummary,
    SegmentBehaviorSummary,
    StockoutSummary,
    WeeklySalesChangeSummary,
)
from src.analysis.promo import promo_lift
from src.analysis.sales import weekly_sales_change
from src.analysis.segments import segment_basket_behavior
from src.analysis.stockouts import detect_stockouts
from src.data import DataAccessError, RetailRepository, get_repository


@dataclass(frozen=True)
class WeeklyAnalysis:
    """All four metric summaries for one week and (optionally) one region."""

    week: int
    region: str | None
    sales: WeeklySalesChangeSummary
    stockouts: StockoutSummary
    promo: PromoLiftSummary
    segments: SegmentBehaviorSummary

    def summaries(self) -> list:
        """The summaries in the form the narrative layer accepts."""
        return [self.sales, self.stockouts, self.promo, self.segments]


def available_weeks(repo: RetailRepository | None = None) -> list[int]:
    try:
        repo = repo or get_repository()
        return sorted(int(w) for w in repo.get_lookup_days()["week"].unique())
    except DataAccessError as exc:
        raise AnalysisError(str(exc)) from exc


def available_regions(repo: RetailRepository | None = None) -> list[str]:
    try:
        repo = repo or get_repository()
        return sorted(repo.get_stores()["region"].unique())
    except DataAccessError as exc:
        raise AnalysisError(str(exc)) from exc


def analyze_week(week: int, region: str | None = None, repo: RetailRepository | None = None) -> WeeklyAnalysis:
    """Run every metric for `week` (restricted to `region` when given)."""
    try:
        repo = repo or get_repository()
        return WeeklyAnalysis(
            week=week,
            region=region,
            sales=weekly_sales_change(repo, week, region),
            stockouts=detect_stockouts(repo, week, region),
            promo=promo_lift(repo, week, region),
            segments=segment_basket_behavior(repo, week, region),
        )
    except DataAccessError as exc:
        raise AnalysisError(str(exc)) from exc
