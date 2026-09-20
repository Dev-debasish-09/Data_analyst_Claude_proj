"""Generates the plain-English weekly report by calling the Claude API.

Data boundary: this is the ONLY module that talks to the API, and it accepts only the
pre-aggregated summary objects from `src.analysis`. The guard runs before any network call.

Reliability:
  * Transient failures (429, 5xx, timeouts, connection errors) are retried by the SDK with
    exponential backoff (`max_retries`).
  * A report that comes back malformed (bad JSON, wrong number of actions, empty fields) is
    re-requested up to `MAX_REPORT_ATTEMPTS` times.
  * Everything else (auth errors, bad requests, refusals, exhausted retries) surfaces as a
    `NarrativeGenerationError` so callers never see SDK-specific exceptions.

Audit: the exact aggregated payload sent is logged to `retail_pulse.narrative.audit`. Raw
records are never logged because they never get here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from config.settings import Settings, get_settings
from src.narrative.errors import NarrativeConfigError, NarrativeGenerationError
from src.narrative.guard import to_payload
from src.narrative.models import NarrativeReport
from src.narrative.prompts import REPORT_SCHEMA, SYSTEM_PROMPT, build_user_prompt

audit_log = logging.getLogger("retail_pulse.narrative.audit")
log = logging.getLogger(__name__)

MAX_SDK_RETRIES = 3  # backoff on 429 / 5xx / timeouts / connection errors
MAX_REPORT_ATTEMPTS = 2  # re-ask when the returned report is unusable
REQUEST_TIMEOUT_SECONDS = 60.0
MAX_TOKENS = 2000
N_ACTIONS = 3


class NarrativeGenerator:
    """Turns analysis summaries into a `NarrativeReport`."""

    def __init__(self, settings: Settings | None = None, client: anthropic.Anthropic | None = None):
        self._settings = settings or get_settings()
        self._client = client  # injected in tests; otherwise built lazily so a missing key
        # only fails when a report is actually requested

    def generate(self, summaries: Any) -> NarrativeReport:
        """Produce a report from one summary or a list of summaries (one per metric)."""
        payload = to_payload(summaries)  # raises RawDataBoundaryError before any network call
        audit_log.info("Sending aggregated payload to Claude API: %s",
                       json.dumps(payload, sort_keys=True))  # fmt: skip
        client = self._get_client()

        last_problem = ""
        for attempt in range(1, MAX_REPORT_ATTEMPTS + 1):
            text = self._call_api(client, payload)
            try:
                return _parse_report(text)
            except ValueError as exc:
                last_problem = str(exc)
                log.warning("Unusable report (attempt %d/%d): %s", attempt, MAX_REPORT_ATTEMPTS, exc)
        raise NarrativeGenerationError(f"Model returned an unusable report: {last_problem}")

    # ---- internals ------------------------------------------------------------------
    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            key = self._settings.anthropic_api_key
            if not key:
                raise NarrativeConfigError(
                    "ANTHROPIC_API_KEY is not set. Set it in the environment (see config/.env.example)."
                )
            self._client = anthropic.Anthropic(
                api_key=key, max_retries=MAX_SDK_RETRIES, timeout=REQUEST_TIMEOUT_SECONDS
            )
        return self._client

    def _call_api(self, client: anthropic.Anthropic, payload: dict[str, Any]) -> str:
        try:
            response = client.messages.create(
                model=self._settings.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_prompt(payload)}],
                output_config={"format": {"type": "json_schema", "schema": REPORT_SCHEMA}},
            )
        except anthropic.AuthenticationError as exc:
            raise NarrativeGenerationError("Anthropic rejected the API key (authentication failed).") from exc
        except anthropic.PermissionDeniedError as exc:
            raise NarrativeGenerationError("The API key lacks permission for this request.") from exc
        except anthropic.NotFoundError as exc:
            raise NarrativeGenerationError(
                f"Model {self._settings.model!r} was not found; check RETAIL_PULSE_MODEL."
            ) from exc
        except anthropic.BadRequestError as exc:
            raise NarrativeGenerationError(f"The API rejected the request: {exc.message}") from exc
        except anthropic.RateLimitError as exc:
            raise NarrativeGenerationError("Rate limited by the API after retries; try again later.") from exc
        except anthropic.APIConnectionError as exc:  # includes timeouts
            raise NarrativeGenerationError("Could not reach the Anthropic API after retries.") from exc
        except anthropic.APIStatusError as exc:
            raise NarrativeGenerationError(f"Anthropic API error ({exc.status_code}) after retries.") from exc

        if response.stop_reason == "refusal":
            raise NarrativeGenerationError("The model declined to produce this report.")
        if response.stop_reason == "max_tokens":
            raise NarrativeGenerationError("The report was cut off (max_tokens); it was not used.")
        return next((b.text for b in response.content if b.type == "text"), "")


def _parse_report(text: str) -> NarrativeReport:
    """Validate the model's JSON. Raises ValueError with a reason when it is unusable."""
    try:
        data = json.loads(text)
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
