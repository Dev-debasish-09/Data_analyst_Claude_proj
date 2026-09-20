"""End-to-end: synthetic database -> data layer -> analysis -> guard -> Claude -> report.

The Claude call is replaced by a stand-in that writes its report FROM THE PAYLOAD IT RECEIVES
(as a real model should). So these tests prove that the facts reaching "the model" are the ones
the analysis produced, and that the report round-trips into a `NarrativeReport`, without ever
asserting exact wording. Key terms are checked case-insensitively.

The one test that talks to the real API is `test_live_*`: it is skipped unless ANTHROPIC_API_KEY
is set, because it costs money.
"""

from __future__ import annotations

import json
import os

import pytest

from config.settings import Environment, Settings, load_settings
from src.analysis import analyze_week
from src.narrative import NarrativeGenerator, NarrativeReport
from tests.fakes import FakeClaude, text_response

SETTINGS = Settings(Environment.DEV, "sqlite:///x", "sk-test", "test-model", "DEBUG")


def _stand_in_model(request: dict):
    """A minimal 'analyst': composes the report using only figures found in the payload."""
    payload = json.loads(request["messages"][0]["content"].split("\n", 1)[1])
    sales, stock = payload["WeeklySalesChangeSummary"], payload["StockoutSummary"]
    promo = payload["PromoLiftSummary"]
    scope = sales["region_filter"] or "All regions"

    pct = sales["total_change_pct"]
    if pct is None:
        headline = f"{scope}: sales for week {sales['week']} have no prior week to compare with"
    else:
        headline = f"{scope} sales {'fell' if pct < 0 else 'rose'} {abs(pct)}% week over week"

    if stock["n_skus_affected"]:
        top = stock["top_skus"][0]
        cause = (f"Likely out-of-stock products: {stock['n_skus_affected']} SKUs, led by "
                 f"{top['department']} ({top['commodity']}), sold zero in "
                 f"{stock['n_stores_affected']} stores.")  # fmt: skip
    else:
        cause = "No stockouts were detected, so the change looks demand-driven."
    if promo["has_promos"]:
        cause += f" Promotions lifted units {promo['unit_lift_pct']}%."

    actions = ["Confirm supply with the distribution centre.", "Reorder the affected products.",
               "Review promotion plans for next week."]  # fmt: skip
    return text_response(json.dumps({"headline": headline, "likely_cause": cause,
                                     "recommended_actions": actions}))  # fmt: skip


def run_pipeline(repo, week: int, region: str | None):
    analysis = analyze_week(week, region, repo=repo)
    client = FakeClaude(responder=_stand_in_model)
    report = NarrativeGenerator(SETTINGS, client).generate(analysis.summaries())
    return analysis, client, report


@pytest.fixture(scope="module")
def result(repo, planted):
    """One pipeline run over the planted stockout week, shared by the tests below."""
    return run_pipeline(repo, planted.stockout_start_week + 1, planted.stockout_region)


class TestPlantedStockoutWeek:
    def test_report_has_the_required_shape(self, result):
        _, _, report = result
        assert isinstance(report, NarrativeReport)
        assert report.headline and report.likely_cause
        assert len(report.recommended_actions) == 3

    def test_the_model_was_told_about_the_stockout(self, result, planted):
        _, client, _ = result
        stock = client.sent_payload["StockoutSummary"]
        assert stock["n_skus_affected"] > 0
        assert [r["region"] for r in stock["by_region"]] == [planted.stockout_region]
        assert {s["department"] for s in stock["top_skus"]} == {"Beverages"}

    def test_report_contains_the_expected_key_terms(self, result, planted):
        _, _, report = result
        text = f"{report.headline} {report.likely_cause}".lower()
        assert planted.stockout_region.lower() in text
        assert "stock" in text  # stockout / out-of-stock
        assert "beverage" in text
        assert "fell" in text  # the West's sales decline

    def test_figures_in_the_report_match_the_analysis(self, result):
        analysis, _, report = result
        assert str(abs(analysis.sales.total_change_pct)) in report.headline
        assert str(analysis.stockouts.n_skus_affected) in report.likely_cause


class TestNormalWeek:
    def test_a_quiet_week_reports_no_stockouts(self, repo):
        analysis, client, report = run_pipeline(repo, 10, None)
        assert client.sent_payload["StockoutSummary"]["n_skus_affected"] == 0
        assert "no stockouts" in report.likely_cause.lower()
        assert "all regions" in report.headline.lower()
        assert analysis.stockouts.n_store_sku_pairs == 0


class TestEdgeWeeks:
    def test_first_week_states_that_no_comparison_exists(self, repo):
        _, client, report = run_pipeline(repo, 1, None)
        assert client.sent_payload["WeeklySalesChangeSummary"]["has_prior_data"] is False
        assert "no prior week" in report.headline.lower()

    def test_promo_free_week_reaches_the_model_as_such(self, repo, planted):
        _, client, report = run_pipeline(repo, planted.no_promo_week, None)
        assert client.sent_payload["PromoLiftSummary"]["has_promos"] is False
        assert "promotions lifted" not in report.likely_cause.lower()


class TestDataBoundary:
    @pytest.mark.parametrize("week, region", [(31, "West"), (10, None), (1, None), (48, "North")])
    def test_no_row_level_data_ever_reaches_the_model(self, repo, week, region):
        _, client, _ = run_pipeline(repo, week, region)
        sent = client.sent_text.lower()
        for forbidden in ("household_id", "basket_id", "trans_time", "customer"):
            assert forbidden not in sent
        assert len(client.sent_text) < 15_000, "a summary, not a data dump"

    def test_one_request_per_report(self, repo):
        _, client, _ = run_pipeline(repo, 31, "West")
        assert len(client.calls) == 1


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY (costs money)")
def test_live_report_mentions_the_planted_anomaly(repo, planted):
    """Real Claude call. Checks for key terms only, never exact wording."""
    analysis = analyze_week(planted.stockout_start_week + 1, planted.stockout_region, repo=repo)
    report = NarrativeGenerator(load_settings()).generate(analysis.summaries())

    assert report.headline.strip() and report.likely_cause.strip()
    assert len(report.recommended_actions) == 3
    text = f"{report.headline} {report.likely_cause} {' '.join(report.recommended_actions)}".lower()
    assert planted.stockout_region.lower() in text
    assert any(term in text for term in ("stockout", "stock-out", "out of stock", "out-of-stock",
                                         "availability", "supply", "beverage"))  # fmt: skip
