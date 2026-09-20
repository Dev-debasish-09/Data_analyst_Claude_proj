"""promo_lift: promoted vs the same items' non-promo baseline."""

from __future__ import annotations

import pytest

from src.analysis import AnalysisError, promo_lift

NORMAL_WEEK = 25


class TestNormalWeek:
    def test_promoted_items_outsell_their_baseline(self, repo):
        s = promo_lift(repo, NORMAL_WEEK)
        assert s.has_promos
        assert s.promo_units > s.baseline_units
        assert s.unit_lift_pct > 100, "the synthetic promos are built to lift volume strongly"

    def test_sales_lift_is_below_unit_lift_because_sales_are_net_of_discount(self, repo):
        s = promo_lift(repo, NORMAL_WEEK)
        assert 0 < s.sales_lift_pct < s.unit_lift_pct

    def test_counts_and_breakdown_are_consistent(self, repo, q):
        s = promo_lift(repo, NORMAL_WEEK)
        assert s.n_promoted_items == q("SELECT COUNT(*) AS n FROM promo WHERE week = :w", w=NORMAL_WEEK)["n"][0]
        assert 0 < s.n_items_with_baseline <= s.n_promoted_items
        assert sum(t.n_items for t in s.by_promo_type) == s.n_items_with_baseline
        assert {t.promo_type for t in s.by_promo_type} <= {"TPR", "Feature", "Display"}
        assert all(t.unit_lift_pct is not None and t.unit_lift_pct > 0 for t in s.by_promo_type)

    def test_lift_matches_an_independent_recalculation(self, repo, q):
        """Pins the definition: each promoted store-SKU vs its own NON-promo weeks in the last 8."""
        week, history = NORMAL_WEEK, range(NORMAL_WEEK - 8, NORMAL_WEEK)
        promos = q("SELECT store_id, upc, week FROM promo WHERE week BETWEEN :a AND :b", a=history[0], b=week)
        units = q("""SELECT i.store_id, i.upc, d.week, SUM(i.quantity) AS u
                     FROM txn_itm i JOIN lookup_day d ON d.day = i.day
                     WHERE d.week BETWEEN :a AND :b GROUP BY i.store_id, i.upc, d.week""",
                  a=history[0], b=week)  # fmt: skip
        sold = {(r.store_id, r.upc, r.week): r.u for r in units.itertuples()}
        on_promo = set(zip(promos["store_id"], promos["upc"], promos["week"]))

        promo_units = baseline_units = evaluated = 0
        for store, upc in promos.loc[promos["week"] == week, ["store_id", "upc"]].itertuples(index=False):
            regular_weeks = [w for w in history if (store, upc, w) not in on_promo]
            if len(regular_weeks) < 3:
                continue
            evaluated += 1
            baseline_units += sum(sold.get((store, upc, w), 0) for w in regular_weeks) / len(regular_weeks)
            promo_units += sold.get((store, upc, week), 0)

        s = promo_lift(repo, week)
        assert s.n_items_with_baseline == evaluated
        assert s.promo_units == pytest.approx(promo_units, abs=0.1)
        assert s.baseline_units == pytest.approx(baseline_units, abs=0.1)
        assert s.unit_lift_pct == pytest.approx((promo_units / baseline_units - 1) * 100, abs=0.1)

    def test_average_discount_is_a_sane_percentage(self, repo):
        assert 5 < promo_lift(repo, NORMAL_WEEK).avg_discount_pct < 40

    def test_region_filter_only_counts_that_regions_promos(self, repo):
        whole = promo_lift(repo, NORMAL_WEEK)
        west = promo_lift(repo, NORMAL_WEEK, region="West")
        assert west.region_filter == "West"
        assert 0 < west.n_promoted_items < whole.n_promoted_items


class TestEdgeCases:
    def test_week_with_no_promos_returns_an_empty_summary(self, repo, planted):
        s = promo_lift(repo, planted.no_promo_week)
        assert s.has_promos is False
        assert s.n_promoted_items == 0 and s.n_items_with_baseline == 0
        assert s.unit_lift_pct is None and s.sales_lift_pct is None and s.avg_discount_pct is None
        assert s.promo_units == 0 and s.baseline_units == 0
        assert s.by_promo_type == ()

    def test_first_week_has_promos_but_no_baseline_to_compare_with(self, repo):
        s = promo_lift(repo, 1)
        assert s.has_promos and s.n_promoted_items > 0
        assert s.n_items_with_baseline == 0
        assert s.unit_lift_pct is None and s.sales_lift_pct is None

    def test_week_right_after_the_promo_free_week_still_works(self, repo, planted):
        s = promo_lift(repo, planted.no_promo_week + 1)
        assert s.has_promos and s.unit_lift_pct is not None

    def test_unknown_inputs_are_rejected(self, repo):
        with pytest.raises(AnalysisError):
            promo_lift(repo, 99)
        with pytest.raises(AnalysisError):
            promo_lift(repo, NORMAL_WEEK, region="Atlantis")
