"""Report engines: provider selection, the local Hugging Face provider, and the fact sheet.

No test here loads a real model (conftest blocks it); the pipeline is always a fake. The single
`local_model` test at the bottom is the opt-in exception.
"""

from __future__ import annotations

import dataclasses
import os
import sys
import types

import pandas as pd
import pytest

from config.settings import ConfigError, Environment, Settings, load_settings
from src.analysis import analyze_week
from src.narrative import (
    ClaudeProvider,
    HuggingFaceProvider,
    NarrativeConfigError,
    NarrativeGenerationError,
    NarrativeGenerator,
    RawDataBoundaryError,
    create_provider,
    describe_provider,
    to_payload,
)
from src.narrative import providers as providers_module
from src.narrative.facts import build_facts

REAL_LOAD_PIPELINE = providers_module._load_pipeline  # captured before conftest blocks it
GOOD = '{"headline": "H", "likely_cause": "C", "recommended_actions": ["a", "b", "c"]}'


def cfg(env=Environment.DEV, key=None, provider="auto", hf_model="org/tiny-model") -> Settings:
    return Settings(env, "sqlite:///x", key, "claude-test", "DEBUG", narrative_provider=provider, hf_model=hf_model)


class FakePipeline:
    """Stands in for a transformers text-generation pipeline. Records how it was called."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls: list[tuple[list, dict]] = []

    def __call__(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.outputs.pop(0)


def generator_with(pipe: FakePipeline) -> NarrativeGenerator:
    return NarrativeGenerator(cfg(), provider=HuggingFaceProvider("org/tiny-model", lambda model_id: pipe))


@pytest.fixture(scope="module")
def analysis(repo):
    return analyze_week(31, "West", repo=repo)


# ------------------------------------------------------------------------------- selection
class TestProviderSelection:
    @pytest.mark.parametrize("env, key, provider, expected", [
        (Environment.DEV, None, "auto", "huggingface"),       # no key in dev -> free local model
        (Environment.DEV, "sk-x", "auto", "claude"),          # a key wins
        (Environment.DEV, "sk-x", "huggingface", "huggingface"),
        (Environment.DEV, None, "claude", "claude"),
        (Environment.STAGING, None, "auto", "claude"),        # non-dev never silently falls back
        (Environment.PROD, "sk-x", "auto", "claude"),
        (Environment.PROD, None, "huggingface", "huggingface"),
    ])  # fmt: skip
    def test_resolution(self, env, key, provider, expected):
        assert cfg(env, key, provider).resolved_provider == expected

    def test_factory_builds_the_matching_provider_without_loading_anything(self):
        assert isinstance(create_provider(cfg(provider="huggingface")), HuggingFaceProvider)
        assert isinstance(create_provider(cfg(key="sk-x")), ClaudeProvider)

    def test_the_engine_is_described_for_the_ui(self):
        assert "Hugging Face" in describe_provider(cfg(hf_model="org/tiny-model"))
        assert "org/tiny-model" in describe_provider(cfg(hf_model="org/tiny-model"))
        assert "Claude" in describe_provider(cfg(key="sk-x"))


class TestSettingsForProviders:
    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        for name in ["RETAIL_PULSE_ENV", "RETAIL_PULSE_DB_URL", "ANTHROPIC_API_KEY",
                     "RETAIL_PULSE_NARRATIVE_PROVIDER", "RETAIL_PULSE_HF_MODEL"]:  # fmt: skip
            monkeypatch.delenv(name, raising=False)

    def test_defaults_need_no_key_in_dev(self):
        s = load_settings()
        assert s.narrative_provider == "auto" and s.resolved_provider == "huggingface"
        assert s.hf_model  # a sensible default model is configured

    def test_the_model_can_be_overridden(self, monkeypatch):
        monkeypatch.setenv("RETAIL_PULSE_HF_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
        assert load_settings().hf_model == "Qwen/Qwen2.5-0.5B-Instruct"

    def test_an_invalid_provider_is_rejected(self, monkeypatch):
        monkeypatch.setenv("RETAIL_PULSE_NARRATIVE_PROVIDER", "openai")
        with pytest.raises(ConfigError, match="NARRATIVE_PROVIDER"):
            load_settings()

    def test_staging_with_claude_still_requires_the_api_key(self, monkeypatch):
        monkeypatch.setenv("RETAIL_PULSE_ENV", "staging")
        monkeypatch.setenv("RETAIL_PULSE_DB_URL", "postgresql://u:p@h/db")
        with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
            load_settings()

    def test_staging_with_the_local_model_does_not_need_an_api_key(self, monkeypatch):
        monkeypatch.setenv("RETAIL_PULSE_ENV", "staging")
        monkeypatch.setenv("RETAIL_PULSE_DB_URL", "postgresql://u:p@h/db")
        monkeypatch.setenv("RETAIL_PULSE_NARRATIVE_PROVIDER", "huggingface")
        assert load_settings().resolved_provider == "huggingface"

    def test_the_db_url_is_still_required_outside_dev(self, monkeypatch):
        monkeypatch.setenv("RETAIL_PULSE_ENV", "prod")
        monkeypatch.setenv("RETAIL_PULSE_NARRATIVE_PROVIDER", "huggingface")
        with pytest.raises(ConfigError, match="RETAIL_PULSE_DB_URL"):
            load_settings()


# ---------------------------------------------------------------------- the local provider
class TestHuggingFaceProvider:
    def test_sends_a_system_prompt_and_a_fact_sheet_never_raw_data(self, analysis):
        pipe = FakePipeline([{"generated_text": GOOD}])
        generator_with(pipe).generate(analysis.summaries())

        messages, kwargs = pipe.calls[0]
        assert [m["role"] for m in messages] == ["system", "user"]
        user = messages[1]["content"]
        assert "West" in user and "Beverages" in user
        assert "household_id" not in str(messages) and "basket_id" not in str(messages)
        assert kwargs["return_full_text"] is False and kwargs["max_new_tokens"] > 0

    def test_first_attempt_is_deterministic_and_the_retry_samples(self, analysis):
        pipe = FakePipeline([{"generated_text": "garbage"}], [{"generated_text": GOOD}])
        report = generator_with(pipe).generate(analysis.summaries())

        assert report.headline == "H" and len(pipe.calls) == 2
        assert pipe.calls[0][1]["do_sample"] is False
        assert pipe.calls[1][1]["do_sample"] is True and pipe.calls[1][1]["temperature"] > 0

    @pytest.mark.parametrize("reply", [
        f"```json\n{GOOD}\n```",
        f"Here is the report:\n{GOOD}\nHope that helps!",
        f"```\n{GOOD}\n```",
    ])  # fmt: skip
    def test_tolerates_the_wrapping_small_models_add_around_json(self, analysis, reply):
        pipe = FakePipeline([{"generated_text": reply}])
        assert generator_with(pipe).generate(analysis.summaries()).headline == "H"
        assert len(pipe.calls) == 1

    def test_gives_up_after_two_unusable_answers(self, analysis):
        pipe = FakePipeline([{"generated_text": "no"}], [{"generated_text": '{"headline": "only"}'}])
        with pytest.raises(NarrativeGenerationError, match="unusable"):
            generator_with(pipe).generate(analysis.summaries())

    @pytest.mark.parametrize("result", [
        [{"generated_text": GOOD}],
        [{"generated_text": [{"role": "user", "content": "q"}, {"role": "assistant", "content": GOOD}]}],
    ])  # fmt: skip
    def test_reads_both_pipeline_result_shapes(self, analysis, result):
        assert generator_with(FakePipeline(result)).generate(analysis.summaries()).headline == "H"

    def test_a_crash_inside_the_model_becomes_a_narrative_error(self, analysis):
        def boom(messages, **kwargs):
            raise RuntimeError("model exploded")

        provider = HuggingFaceProvider("m", lambda model_id: boom)
        with pytest.raises(NarrativeGenerationError, match="model exploded"):
            NarrativeGenerator(cfg(), provider=provider).generate(analysis.summaries())

    def test_running_out_of_memory_becomes_a_narrative_error(self, analysis):
        def oom(messages, **kwargs):
            raise MemoryError

        provider = HuggingFaceProvider("m", lambda model_id: oom)
        with pytest.raises(NarrativeGenerationError, match="memory"):
            NarrativeGenerator(cfg(), provider=provider).generate(analysis.summaries())


class TestModelLoading:
    """The real loader, with `transformers` swapped for a fake module."""

    @pytest.fixture(autouse=True)
    def fresh_cache(self, monkeypatch):
        monkeypatch.setattr(providers_module, "_pipelines", {})

    def test_missing_extras_give_an_actionable_message(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "transformers", None)  # makes `import transformers` fail
        with pytest.raises(NarrativeConfigError, match=r"\.\[hf\]"):
            REAL_LOAD_PIPELINE("any/model")

    def test_load_failures_become_narrative_errors(self, monkeypatch):
        def failing_pipeline(*args, **kwargs):
            raise OSError("model not found on the hub")

        monkeypatch.setitem(sys.modules, "transformers", types.SimpleNamespace(pipeline=failing_pipeline))
        with pytest.raises(NarrativeGenerationError, match="Could not load"):
            REAL_LOAD_PIPELINE("any/model")

    def test_a_model_is_loaded_once_and_reused(self, monkeypatch):
        loads = []

        def counting_pipeline(task, model, **kwargs):
            loads.append(model)
            return object()

        monkeypatch.setitem(sys.modules, "transformers", types.SimpleNamespace(pipeline=counting_pipeline))
        first = REAL_LOAD_PIPELINE("org/model")
        assert REAL_LOAD_PIPELINE("org/model") is first
        assert loads == ["org/model"]


class TestBoundaryAppliesToEveryProvider:
    def test_the_guard_fires_before_any_model_is_loaded(self):
        loaded = []
        provider = HuggingFaceProvider("m", lambda model_id: loaded.append(model_id) or FakePipeline())
        with pytest.raises(RawDataBoundaryError):
            NarrativeGenerator(cfg(), provider=provider).generate(pd.DataFrame({"household_id": [1, 2]}))
        assert loaded == []

    def test_smuggled_row_data_is_rejected_before_the_local_model_sees_it(self, analysis):
        evil = dataclasses.replace(analysis.stockouts, top_skus=tuple({"household_id": i} for i in range(30)))
        pipe = FakePipeline()
        with pytest.raises(RawDataBoundaryError):
            generator_with(pipe).generate([evil])
        assert pipe.calls == []


# ------------------------------------------------------------------------------ fact sheet
class TestFactSheet:
    def test_states_the_key_figures_in_words(self, analysis):
        facts = build_facts(to_payload(analysis.summaries()))
        s, st = analysis.sales, analysis.stockouts
        assert f"{s.total_change_pct:+.1f}%" in facts
        assert f"${s.total_sales:,.0f}" in facts
        assert str(st.n_skus_affected) in facts and "Beverages" in facts and "West" in facts
        assert "Household segments" in facts

    def test_leads_with_the_stockout_finding_when_there_is_one(self, analysis):
        facts = build_facts(to_payload(analysis.summaries()))
        assert facts.startswith("MOST IMPORTANT FINDING")

    def test_a_quiet_week_says_there_are_no_stockouts(self, repo):
        facts = build_facts(to_payload(analyze_week(10, repo=repo).summaries()))
        assert "no suspected stockouts" in facts and "MOST IMPORTANT" not in facts

    def test_first_week_says_no_comparison_exists(self, repo):
        facts = build_facts(to_payload(analyze_week(1, repo=repo).summaries()))
        assert "no prior week" in facts and "not enough sales history" in facts

    def test_promo_free_week(self, repo, planted):
        facts = build_facts(to_payload(analyze_week(planted.no_promo_week, repo=repo).summaries()))
        assert "Promotions: none this week" in facts

    def test_contains_no_identifiers(self, analysis):
        facts = build_facts(to_payload(analysis.summaries())).lower()
        for forbidden in ("household_id", "basket_id", "trans_time", "store_id"):
            assert forbidden not in facts


# ----------------------------------------------------------------- opt-in: a real local model
@pytest.mark.local_model
@pytest.mark.skipif(not os.getenv("RETAIL_PULSE_TEST_LOCAL_MODEL"),
                    reason="downloads and runs a real model; set RETAIL_PULSE_TEST_LOCAL_MODEL=1")  # fmt: skip
def test_real_local_model_mentions_the_planted_anomaly(analysis):
    """Runs the actual Hugging Face model (about a minute on a laptop CPU). Key terms only."""
    report = NarrativeGenerator(load_settings()).generate(analysis.summaries())
    text = f"{report.headline} {report.likely_cause} {' '.join(report.recommended_actions)}".lower()
    assert len(report.recommended_actions) == 3
    assert "west" in text
    assert any(term in text for term in ("stockout", "out of stock", "unavailable", "beverage"))
