"""The data-boundary guard: only pre-aggregated summaries may reach the Claude API."""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from src.analysis import analyze_week
from src.narrative import RawDataBoundaryError, assert_aggregated_only, to_payload


@pytest.fixture(scope="module")
def analysis(repo):
    return analyze_week(31, "West", repo=repo)


class TestAcceptsAggregates:
    def test_real_summaries_pass(self, analysis):
        payload = to_payload(analysis.summaries())
        assert set(payload) == {"WeeklySalesChangeSummary", "StockoutSummary",
                                "PromoLiftSummary", "SegmentBehaviorSummary"}  # fmt: skip

    def test_a_single_summary_passes(self, analysis):
        assert list(to_payload(analysis.stockouts)) == ["StockoutSummary"]

    def test_counts_such_as_n_households_are_allowed(self, analysis):
        assert "n_households" in str(to_payload(analysis.segments))

    def test_payload_is_small(self, analysis):
        import json

        assert len(json.dumps(to_payload(analysis.summaries()))) < 10_000


class TestRejectsRawData:
    @pytest.mark.parametrize("bad", [
        pd.DataFrame({"household_id": [1, 2, 3]}),
        {"household_id": [1, 2, 3]},
        [{"basket_id": 1, "household_id": 7}],
        list(range(500)),
        "raw text",
        None,
    ])  # fmt: skip
    def test_anything_that_is_not_a_summary_is_rejected(self, bad):
        with pytest.raises(RawDataBoundaryError):
            to_payload(bad)

    def test_empty_input_is_rejected(self):
        with pytest.raises(RawDataBoundaryError):
            to_payload([])

    def test_the_same_summary_type_twice_is_rejected(self, analysis):
        with pytest.raises(RawDataBoundaryError, match="Duplicate"):
            to_payload([analysis.sales, analysis.sales])


class TestRejectsRowDataSmuggledIntoASummary:
    """A legitimate summary type whose fields have been stuffed with row-level data."""

    def _with(self, analysis, **fields):
        return dataclasses.replace(analysis.stockouts, **fields)

    def test_household_id_level_list(self, analysis):
        rows = tuple({"household_id": i} for i in range(30))
        with pytest.raises(RawDataBoundaryError):
            to_payload(self._with(analysis, top_skus=rows))

    def test_a_long_list_of_ids(self, analysis):
        with pytest.raises(RawDataBoundaryError, match="record-level list"):
            to_payload(self._with(analysis, top_skus=tuple(range(50))))

    @pytest.mark.parametrize("key", ["household_id", "basket_ids", "customer", "loyalty_card", "trans_time", "store_id"])
    def test_identifier_like_keys(self, analysis, key):
        with pytest.raises(RawDataBoundaryError, match="identifier"):
            to_payload(self._with(analysis, by_region=({key: 1},)))

    def test_a_dataframe_field(self, analysis):
        with pytest.raises(RawDataBoundaryError, match="DataFrame"):
            to_payload(self._with(analysis, top_skus=pd.DataFrame({"a": [1]})))

    def test_an_oversized_payload(self, analysis):
        with pytest.raises(RawDataBoundaryError, match="too large"):
            to_payload(self._with(analysis, by_region=tuple({"note": "x" * 2000} for _ in range(20))))

    def test_excessive_nesting(self):
        deep: dict = {}
        node = deep
        for _ in range(10):
            node["k"] = {}
            node = node["k"]
        with pytest.raises(RawDataBoundaryError, match="nesting"):
            assert_aggregated_only(deep)


def test_guard_runs_before_any_client_is_created():
    """The error must fire before credentials or the network are touched."""
    from config.settings import Environment, Settings
    from src.narrative import NarrativeGenerator

    no_key = Settings(Environment.DEV, "sqlite:///x", None, "m", "DEBUG")
    with pytest.raises(RawDataBoundaryError):  # not NarrativeConfigError
        NarrativeGenerator(no_key).generate(pd.DataFrame({"household_id": [1]}))
