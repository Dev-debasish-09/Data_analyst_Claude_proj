"""detect_stockouts: finds the planted regional stockout, stays quiet otherwise."""

from __future__ import annotations

import pytest

from src.analysis import AnalysisError, detect_stockouts

NORMAL_WEEKS = [4, 10, 25, 29, 34, 35, 45, 52]


class TestPlantedAnomaly:
    @pytest.mark.parametrize("week", range(30, 34))
    def test_outage_weeks_flag_the_planted_skus_in_the_planted_region(self, repo, planted, week):
        s = detect_stockouts(repo, week, top_n=50)

        assert s.has_history
        assert [r.region for r in s.by_region] == [planted.stockout_region], "only the affected region"
        assert s.n_store_sku_pairs >= 25, "most of the planted store-SKU pairs are found"
        assert s.n_store_sku_pairs <= len(planted.stockout_pairs), "and nothing beyond them"
        assert s.est_sales_at_risk > 0

    @pytest.mark.parametrize("week", range(30, 34))
    def test_every_flagged_sku_is_a_planted_beverage(self, repo, planted, week):
        s = detect_stockouts(repo, week, top_n=50)
        assert s.top_skus
        assert {k.upc for k in s.top_skus} <= planted.stockout_upcs
        assert {k.department for k in s.top_skus} == {"Beverages"}

    def test_affected_stores_are_all_stores_of_the_region(self, repo, planted):
        s = detect_stockouts(repo, planted.stockout_start_week)
        region_stores = {store for store, _ in planted.stockout_pairs}
        assert s.n_stores_affected == len(region_stores)

    def test_region_filter_on_the_affected_region_still_finds_it(self, repo, planted):
        s = detect_stockouts(repo, planted.stockout_start_week + 1, region=planted.stockout_region)
        assert s.n_store_sku_pairs >= 25

    def test_region_filter_on_an_unaffected_region_finds_nothing(self, repo, planted):
        s = detect_stockouts(repo, planted.stockout_start_week + 1, region="East")
        assert s.n_store_sku_pairs == 0 and s.by_region == ()

    def test_recovery_week_is_clean(self, repo, planted):
        assert detect_stockouts(repo, planted.stockout_end_week + 1).n_store_sku_pairs == 0


class TestNormalWeeks:
    @pytest.mark.parametrize("week", NORMAL_WEEKS)
    def test_no_false_alarms(self, repo, week):
        s = detect_stockouts(repo, week)
        assert s.has_history
        assert s.n_store_sku_pairs == 0
        assert s.n_skus_affected == 0 and s.est_sales_at_risk == 0.0
        assert s.by_region == () and s.top_skus == ()


class TestEdgeCases:
    @pytest.mark.parametrize("week", [1, 2, 3])
    def test_too_little_history_flags_nothing(self, repo, week):
        s = detect_stockouts(repo, week)
        assert s.has_history is False
        assert s.n_store_sku_pairs == 0

    def test_first_week_with_enough_history(self, repo):
        assert detect_stockouts(repo, 4).has_history is True

    def test_higher_threshold_is_stricter(self, repo, planted):
        loose = detect_stockouts(repo, planted.stockout_start_week)
        strict = detect_stockouts(repo, planted.stockout_start_week, min_baseline_units=10_000)
        assert loose.n_store_sku_pairs > 0
        assert strict.n_store_sku_pairs == 0

    def test_unknown_inputs_are_rejected(self, repo):
        with pytest.raises(AnalysisError):
            detect_stockouts(repo, 99)
        with pytest.raises(AnalysisError):
            detect_stockouts(repo, 10, region="Atlantis")
