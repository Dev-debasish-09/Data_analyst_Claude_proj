"""NarrativeGenerator: request shape, report validation, retries and error mapping."""

from __future__ import annotations

import logging

import anthropic
import pytest

from config.settings import Environment, Settings
from src.analysis import analyze_week
from src.narrative import (
    NarrativeConfigError,
    NarrativeGenerationError,
    NarrativeGenerator,
    NarrativeReport,
)
from tests.fakes import FakeClaude, api_error, report_json, text_response


@pytest.fixture(scope="module")
def summaries(repo):
    return analyze_week(31, "West", repo=repo).summaries()


def settings(key: str | None = "sk-test") -> Settings:
    return Settings(Environment.DEV, "sqlite:///x", key, "test-model", "DEBUG")


def generate(client: FakeClaude, summaries) -> NarrativeReport:
    return NarrativeGenerator(settings(), client).generate(summaries)


class TestRequest:
    def test_uses_the_configured_model_and_a_json_schema(self, summaries):
        client = FakeClaude(text_response(report_json()))
        generate(client, summaries)
        call = client.calls[0]
        assert call["model"] == "test-model"
        assert call["output_config"]["format"]["type"] == "json_schema"
        assert call["max_tokens"] > 0

    def test_prompt_contains_only_aggregates(self, summaries):
        client = FakeClaude(text_response(report_json()))
        generate(client, summaries)
        assert "household_id" not in client.sent_text and "basket_id" not in client.sent_text
        assert set(client.sent_payload) == {"WeeklySalesChangeSummary", "StockoutSummary",
                                            "PromoLiftSummary", "SegmentBehaviorSummary"}  # fmt: skip

    def test_the_payload_sent_is_written_to_the_audit_log(self, summaries, caplog):
        with caplog.at_level(logging.INFO, logger="retail_pulse.narrative.audit"):
            generate(FakeClaude(text_response(report_json())), summaries)
        assert any("StockoutSummary" in r.message for r in caplog.records)


class TestReport:
    def test_parses_a_valid_report(self, summaries):
        r = generate(FakeClaude(text_response(report_json("  Head  ", "Why.", ("a", "b", "c")))), summaries)
        assert r == NarrativeReport("Head", "Why.", ("a", "b", "c"))

    @pytest.mark.parametrize("bad", [
        "not json at all",
        "[1, 2, 3]",
        report_json(headline=""),
        report_json(cause="  "),
        report_json(actions=("only", "two")),
        report_json(actions=("a", "b", "c", "d")),
        report_json(actions=("a", "", "c")),
    ])  # fmt: skip
    def test_an_unusable_report_is_retried_once_then_reported_as_an_error(self, summaries, bad):
        client = FakeClaude(text_response(bad), text_response(bad))
        with pytest.raises(NarrativeGenerationError, match="unusable"):
            generate(client, summaries)
        assert len(client.calls) == 2

    def test_a_malformed_first_answer_is_recovered_by_the_retry(self, summaries):
        client = FakeClaude(text_response("oops"), text_response(report_json("Recovered")))
        assert generate(client, summaries).headline == "Recovered"
        assert len(client.calls) == 2


class TestFailures:
    @pytest.mark.parametrize("stop, message", [("refusal", "declined"), ("max_tokens", "cut off")])
    def test_refusal_and_truncation_are_errors(self, summaries, stop, message):
        with pytest.raises(NarrativeGenerationError, match=message):
            generate(FakeClaude(text_response(report_json(), stop)), summaries)

    @pytest.mark.parametrize("exc_class, status, message", [
        (anthropic.AuthenticationError, 401, "authentication"),
        (anthropic.PermissionDeniedError, 403, "permission"),
        (anthropic.NotFoundError, 404, "not found"),
        (anthropic.BadRequestError, 400, "rejected the request"),
        (anthropic.RateLimitError, 429, "Rate limited"),
        (anthropic.InternalServerError, 500, "API error"),
    ])  # fmt: skip
    def test_sdk_errors_become_narrative_errors(self, summaries, exc_class, status, message):
        with pytest.raises(NarrativeGenerationError, match=message):
            generate(FakeClaude(api_error(exc_class, status)), summaries)

    def test_connection_errors_become_narrative_errors(self, summaries):
        from tests.fakes import httpx

        exc = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
        with pytest.raises(NarrativeGenerationError, match="reach"):
            generate(FakeClaude(exc), summaries)

    def test_no_sdk_exception_ever_escapes(self, summaries):
        with pytest.raises(NarrativeGenerationError) as info:
            generate(FakeClaude(api_error(anthropic.RateLimitError, 429)), summaries)
        assert not isinstance(info.value, anthropic.APIError)


class TestCredentials:
    def test_a_missing_key_only_fails_when_a_report_is_requested(self, summaries):
        generator = NarrativeGenerator(settings(key=None))  # constructing is fine
        with pytest.raises(NarrativeConfigError, match="ANTHROPIC_API_KEY"):
            generator.generate(summaries)

    def test_the_real_client_is_built_with_retries_and_a_timeout(self):
        client = NarrativeGenerator(settings("sk-test"))._get_client()
        assert client.max_retries >= 2
        assert client.timeout is not None
