"""Generates the plain-English weekly report from aggregated summaries.

Data boundary: this is the ONLY entry point to a report-writing engine, and it accepts only the
pre-aggregated summary objects from `src.analysis`. The guard runs first, before any provider is
created, any model is loaded or any network call is made. That holds for every provider.

Engines (see `providers.py`): Claude via the Anthropic API, or a small local Hugging Face model.

Reliability:
  * Provider-level failures (rate limits, timeouts, refusals, missing key, model load errors)
    surface as `NarrativeGenerationError` / `NarrativeConfigError`; callers never see SDK types.
  * A report that comes back unusable (not JSON, empty fields, not exactly 3 actions) is
    re-requested up to `MAX_REPORT_ATTEMPTS` times.

Audit: the exact aggregated payload sent is logged to `retail_pulse.narrative.audit`, with the
engine name. Raw records are never logged because they never get here.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import anthropic

from config.settings import Settings, get_settings
from src.narrative.errors import NarrativeGenerationError
from src.narrative.guard import to_payload
from src.narrative.models import NarrativeReport
from src.narrative.providers import ClaudeProvider, NarrativeProvider, create_provider

audit_log = logging.getLogger("retail_pulse.narrative.audit")
log = logging.getLogger(__name__)

MAX_REPORT_ATTEMPTS = 2  # re-ask when the returned report is unusable
N_ACTIONS = 3


class NarrativeGenerator:
    """Turns analysis summaries into a `NarrativeReport`."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: anthropic.Anthropic | None = None,
        provider: NarrativeProvider | None = None,
    ):
        """`provider` overrides the configured engine; `client` injects an Anthropic client
        (both are for tests). By default the engine comes from `settings`."""
        self._settings = settings or get_settings()
        if provider is None and client is not None:
            provider = ClaudeProvider(self._settings, client)
        self._provider = provider

    @property
    def provider(self) -> NarrativeProvider:
        if self._provider is None:
            self._provider = create_provider(self._settings)
        return self._provider

    def generate(self, summaries: Any) -> NarrativeReport:
        """Produce a report from one summary or a list of summaries (one per metric)."""
        payload = to_payload(summaries)  # raises RawDataBoundaryError before anything else happens
        provider = self.provider
        audit_log.info("Sending aggregated payload to %s: %s", provider.name,
                       json.dumps(payload, sort_keys=True))  # fmt: skip

        last_problem = ""
        for attempt in range(1, MAX_REPORT_ATTEMPTS + 1):
            text = provider.complete(payload, attempt)
            try:
                return _parse_report(text)
            except ValueError as exc:
                last_problem = str(exc)
                log.warning("Unusable report (attempt %d/%d): %s", attempt, MAX_REPORT_ATTEMPTS, exc)
        raise NarrativeGenerationError(f"Model returned an unusable report: {last_problem}")


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _extract_json(text: str) -> str:
    """Small models often wrap JSON in code fences or add a sentence around it; peel that off."""
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    return cleaned[start : end + 1] if start != -1 and end > start else cleaned


def _parse_report(text: str) -> NarrativeReport:
    """Validate the model's JSON. Raises ValueError with a reason when it is unusable."""
    try:
        data = json.loads(_extract_json(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON ({exc.msg})") from exc
    if not isinstance(data, dict):
        raise ValueError("top-level JSON is not an object")

    headline = data.get("headline")
    cause = data.get("likely_cause")
    actions = data.get("recommended_actions")
    if not isinstance(headline, str) or not headline.strip():
        raise ValueError("missing headline")
    if not isinstance(cause, str) or not cause.strip():
        raise ValueError("missing likely_cause")
    if (not isinstance(actions, list) or len(actions) != N_ACTIONS
            or not all(isinstance(a, str) and a.strip() for a in actions)):  # fmt: skip
        raise ValueError(f"recommended_actions must be exactly {N_ACTIONS} non-empty strings")
    return NarrativeReport(headline.strip(), cause.strip(), tuple(a.strip() for a in actions))
