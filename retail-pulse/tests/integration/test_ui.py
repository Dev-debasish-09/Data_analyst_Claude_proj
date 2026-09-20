"""Streamlit app smoke tests, driven headlessly with Streamlit's AppTest.

The app is pointed at the temp synthetic database through RETAIL_PULSE_DB_URL, exactly the way
a real deployment is configured. The Claude call is stubbed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from config.settings import get_settings
from src.narrative import NarrativeGenerator, NarrativeReport

APP = Path(__file__).resolve().parents[2] / "src" / "ui" / "app.py"  # absolute: works from any cwd


@pytest.fixture(autouse=True)
def app_env(monkeypatch, db_path):
    monkeypatch.setenv("RETAIL_PULSE_ENV", "dev")
    monkeypatch.setenv("RETAIL_PULSE_DB_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    st.cache_data.clear()
    yield
    get_settings.cache_clear()
    st.cache_data.clear()


def launch() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=90).run()


def cards(at: AppTest) -> dict:
    return {m.label: m for m in at.metric}


def select(at: AppTest, week: int | None = None, region: str | None = None) -> AppTest:
    if week is not None:
        at.selectbox[0].set_value(week).run()
    if region is not None:
        at.selectbox[1].set_value(region).run()
    return at


def test_opens_on_the_latest_week_with_four_metric_cards():
    at = launch()
    assert not at.exception
    assert at.selectbox[0].value == 52 and at.selectbox[1].value == "All regions"
    assert set(cards(at)) == {"Total sales", "Suspected stockouts", "Promo unit lift", "Top segment"}


def test_planted_stockout_week_shows_up_on_the_cards(planted):
    at = select(launch(), planted.stockout_start_week + 1, planted.stockout_region)
    assert not at.exception
    c = cards(at)
    assert c["Total sales"].delta.startswith("-"), "West sales fell"
    n = int(re.match(r"(\d+) SKUs", c["Suspected stockouts"].value).group(1))
    assert n > 0


def test_a_quiet_week_shows_no_stockouts():
    c = cards(select(launch(), 10))
    assert c["Suspected stockouts"].value.startswith("0 SKUs")


def test_first_week_and_promo_free_week_degrade_gracefully(planted):
    at = select(launch(), 1)
    assert not at.exception
    assert cards(at)["Suspected stockouts"].value == "n/a"

    at = select(at, planted.no_promo_week)
    assert not at.exception
    assert cards(at)["Promo unit lift"].value == "No promos"


def test_report_without_an_api_key_shows_a_warning_not_a_crash():
    at = launch()
    at.button[0].click().run()
    assert not at.exception
    assert any("API key" in w.value for w in at.warning)


def test_report_is_displayed_and_hidden_when_the_selection_changes(monkeypatch):
    stub = NarrativeReport("Headline text", "Because reasons.", ("Do one", "Do two", "Do three"))
    monkeypatch.setattr(NarrativeGenerator, "generate", lambda self, summaries: stub)

    at = launch()
    at.button[0].click().run()
    assert [s.value for s in at.success] == ["Headline text"]
    assert any("Do two" in m.value for m in at.markdown)

    select(at, region="East")
    assert not at.success, "a report for another selection must not be shown"


def test_the_data_sent_to_claude_is_disclosed_and_aggregated():
    at = launch()
    assert any("What gets sent to Claude" in e.label for e in at.expander)
    assert not at.exception


def test_the_ui_layer_only_imports_analysis_and_narrative():
    """Architecture rule: no business logic, no direct data or API access in src/ui."""
    source = APP.read_text(encoding="utf-8")
    imported = set(re.findall(r"^\s*from (src\.\w+|config\.\w+) import", source, re.MULTILINE))
    assert imported <= {"src.analysis", "src.narrative", "config.settings"}
    assert "anthropic" not in source and "sqlite3" not in source
