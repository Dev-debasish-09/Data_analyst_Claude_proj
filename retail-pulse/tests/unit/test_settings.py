"""Environment-aware settings: dev defaults, strict staging/prod, secret masking."""

from __future__ import annotations

import pytest

from config.settings import ConfigError, Environment, Settings, get_settings, load_settings

ENV_VARS = ["RETAIL_PULSE_ENV", "RETAIL_PULSE_DB_URL", "ANTHROPIC_API_KEY",
            "RETAIL_PULSE_MODEL", "RETAIL_PULSE_LOG_LEVEL"]  # fmt: skip


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_dev_works_with_nothing_set():
    s = load_settings()
    assert s.env is Environment.DEV and s.is_dev
    assert s.db_url.startswith("sqlite:///")
    assert s.anthropic_api_key is None
    assert s.log_level == "DEBUG"


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_non_dev_refuses_to_start_without_required_variables(monkeypatch, env):
    monkeypatch.setenv("RETAIL_PULSE_ENV", env)
    with pytest.raises(ConfigError, match="RETAIL_PULSE_DB_URL.*ANTHROPIC_API_KEY"):
        load_settings()


def test_non_dev_starts_when_fully_configured(monkeypatch):
    monkeypatch.setenv("RETAIL_PULSE_ENV", "prod")
    monkeypatch.setenv("RETAIL_PULSE_DB_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    s = load_settings()
    assert s.env is Environment.PROD and not s.is_dev
    assert s.log_level == "WARNING"


def test_environment_name_is_case_insensitive_and_validated(monkeypatch):
    monkeypatch.setenv("RETAIL_PULSE_ENV", " DEV ")
    assert load_settings().env is Environment.DEV
    monkeypatch.setenv("RETAIL_PULSE_ENV", "production")
    with pytest.raises(ConfigError, match="Invalid RETAIL_PULSE_ENV"):
        load_settings()


def test_overrides_are_respected(monkeypatch):
    monkeypatch.setenv("RETAIL_PULSE_MODEL", "some-model")
    monkeypatch.setenv("RETAIL_PULSE_LOG_LEVEL", "error")
    s = load_settings()
    assert s.model == "some-model" and s.log_level == "ERROR"


def test_an_empty_api_key_counts_as_missing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert load_settings().anthropic_api_key is None


class TestSecretsNeverAppearInText:
    def _prod(self):
        return Settings(Environment.PROD, "postgresql://svc_user:S3cr3t!Pass@warehouse:5432/retail",
                        "sk-test-verysecret", "m", "INFO")  # fmt: skip

    def test_repr_masks_the_api_key_and_db_password(self):
        text = repr(self._prod())
        assert "sk-test-verysecret" not in text and "S3cr3t" not in text
        assert "svc_user" in text and "warehouse" in text, "non-secret parts stay readable"

    def test_str_and_fstring_are_masked_too(self):
        s = self._prod()
        assert "verysecret" not in str(s) and "verysecret" not in f"{s}"
