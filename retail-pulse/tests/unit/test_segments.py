"""segment_basket_behavior: per-segment basket metrics."""

from __future__ import annotations

import pytest

from src.analysis import AnalysisError, segment_basket_behavior

NORMAL_WEEK = 48
SEGMENTS = {"Budget Families", "Affluent Households", "Young Singles", "Established Couples"}


class TestNormalWeek:
    def test_reports_every_segment_sorted_by_sales(self, repo):
        s = segment_basket_behavior(repo, NORMAL_WEEK)
        assert {x.segment_name for x in s.segments} == SEGMENTS
        sales = [x.total_sales for x in s.segments]
        assert sales == sorted(sales, reverse=True)

    def test_baskets_and_sales_match_independent_sql(self, repo, q):
        s = segment_basket_behavior(repo, NORMAL_WEEK)
        row = q("SELECT COUNT(*) AS n, SUM(total_basket_value) AS v FROM txn_hdr WHERE week = :w", w=NORMAL_WEEK)
        assert sum(x.n_baskets for x in s.segments) == row["n"][0]
        assert sum(x.total_sales for x in s.segments) == pytest.approx(row["v"][0], abs=1.0)

    def test_shares_of_sales_add_to_100(self, repo):
        s = segment_basket_behavior(repo, NORMAL_WEEK)
        assert sum(x.share_of_sales_pct for x in s.segments) == pytest.approx(100.0, abs=0.6)

    def test_metrics_are_plausible_and_internally_consistent(self, repo):
        for x in segment_basket_behavior(repo, NORMAL_WEEK).segments:
            assert x.avg_basket_value == pytest.approx(x.total_sales / x.n_baskets, abs=0.01)
            assert 1 < x.avg_items_per_basket < 20
            assert 0 <= x.promo_item_share_pct <= 100
            assert 0 < x.n_households <= x.n_baskets

    def test_basket_change_is_measured_against_the_prior_week(self, repo):
        for x in segment_basket_behavior(repo, NORMAL_WEEK).segments:
            expected = (x.avg_basket_value - x.prior_avg_basket_value) / x.prior_avg_basket_value * 100
            assert x.basket_value_change_pct == pytest.approx(expected, abs=0.15)

    def test_family_baskets_are_larger_than_single_baskets(self, repo):
        by_name = {x.segment_name: x for x in segment_basket_behavior(repo, NORMAL_WEEK).segments}
        assert by_name["Budget Families"].avg_items_per_basket > by_name["Young Singles"].avg_items_per_basket

    def test_region_filter_reduces_the_basket_count(self, repo):
        whole = sum(x.n_baskets for x in segment_basket_behavior(repo, NORMAL_WEEK).segments)
        north = segment_basket_behavior(repo, NORMAL_WEEK, region="North")
        assert north.region_filter == "North"
        assert 0 < sum(x.n_baskets for x in north.segments) < whole


class TestEdgeCases:
    def test_first_week_has_no_prior_comparison(self, repo):
        s = segment_basket_behavior(repo, 1)
        assert s.prior_week is None
        assert s.segments
        assert all(x.prior_avg_basket_value is None and x.basket_value_change_pct is None for x in s.segments)

    def test_unknown_inputs_are_rejected(self, repo):
        with pytest.raises(AnalysisError):
            segment_basket_behavior(repo, 99)
        with pytest.raises(AnalysisError):
            segment_basket_behavior(repo, NORMAL_WEEK, region="Atlantis")
