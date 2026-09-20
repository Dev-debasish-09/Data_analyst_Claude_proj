"""weekly_sales_change: totals, prior-week comparison, edge cases and the planted anomaly."""

from __future__ import annotations

import pytest

from src.analysis import AnalysisError, weekly_sales_change

NORMAL_WEEK = 10


def _independent_sales(q, week: int, region: str | None = None) -> float:
    sql = """SELECT SUM(i.sales_value) AS v FROM txn_itm i
             JOIN lookup_day d ON d.day = i.day JOIN store s ON s.store_id = i.store_id
             WHERE d.week = :w AND (:r IS NULL OR s.region = :r)"""
    return float(q(sql, w=week, r=region)["v"][0])


class TestNormalWeek:
    def test_total_matches_independent_sql(self, repo, q):
        s = weekly_sales_change(repo, NORMAL_WEEK)
        assert s.total_sales == pytest.approx(_independent_sales(q, NORMAL_WEEK), abs=0.01)
        assert s.prior_total_sales == pytest.approx(_independent_sales(q, NORMAL_WEEK - 1), abs=0.01)

    def test_percent_change_is_consistent_with_totals(self, repo):
        s = weekly_sales_change(repo, NORMAL_WEEK)
        expected = (s.total_sales - s.prior_total_sales) / s.prior_total_sales * 100
        assert s.has_prior_data and s.prior_week == NORMAL_WEEK - 1
        assert s.total_change_pct == pytest.approx(expected, abs=0.06)

    def test_department_and_region_breakdowns_add_up_to_the_total(self, repo):
        s = weekly_sales_change(repo, NORMAL_WEEK)
        assert sum(d.sales for d in s.by_department) == pytest.approx(s.total_sales, abs=1.0)
        assert sum(r.sales for r in s.by_region) == pytest.approx(s.total_sales, abs=1.0)
        assert len(s.by_department) == 8 and len(s.by_region) == 4

    def test_top_movers_are_ranked_by_absolute_dollar_change(self, repo):
        movers = weekly_sales_change(repo, NORMAL_WEEK, top_n=5).top_movers
        assert len(movers) == 5
        changes = [abs(m.change_amount) for m in movers]
        assert changes == sorted(changes, reverse=True)

    def test_region_filter_restricts_everything_to_that_region(self, repo, q):
        s = weekly_sales_change(repo, NORMAL_WEEK, region="East")
        assert s.region_filter == "East"
        assert [r.region for r in s.by_region] == ["East"]
        assert s.total_sales == pytest.approx(_independent_sales(q, NORMAL_WEEK, "East"), abs=0.01)


class TestEdgeCases:
    def test_first_week_has_no_prior_and_no_invented_changes(self, repo):
        s = weekly_sales_change(repo, 1)
        assert s.has_prior_data is False
        assert s.prior_week is None and s.prior_total_sales is None and s.total_change_pct is None
        assert s.total_sales > 0
        assert all(d.change_pct is None and d.prior_sales is None for d in s.by_department)
        assert all(m.change_pct is None for m in s.top_movers)

    def test_last_week_works(self, repo):
        assert weekly_sales_change(repo, 52).has_prior_data

    @pytest.mark.parametrize("week", [0, 53, 999, -1])
    def test_unknown_week_is_rejected(self, repo, week):
        with pytest.raises(AnalysisError, match="Unknown week"):
            weekly_sales_change(repo, week)

    def test_unknown_region_is_rejected(self, repo):
        with pytest.raises(AnalysisError, match="Unknown region"):
            weekly_sales_change(repo, NORMAL_WEEK, region="Atlantis")


class TestPlantedAnomaly:
    def test_stockout_region_beverages_fall_while_other_regions_rise(self, repo, planted):
        """First outage week: West Beverages drop vs the week before; East does not."""
        s = weekly_sales_change(repo, planted.stockout_start_week, top_n=40)
        cell = {(m.department, m.region): m.change_pct for m in s.top_movers}
        west = cell[("Beverages", planted.stockout_region)]
        east = cell[("Beverages", "East")]
        assert west < -10, f"West Beverages should drop sharply, got {west}%"
        assert west < east - 20

    def test_stockout_region_total_falls_against_the_other_regions(self, repo, planted):
        s = weekly_sales_change(repo, planted.stockout_start_week + 1)
        by_region = {r.region: r.change_pct for r in s.by_region}
        assert by_region[planted.stockout_region] < min(v for k, v in by_region.items() if k != planted.stockout_region)
