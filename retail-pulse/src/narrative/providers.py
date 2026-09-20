"""Report-writing engines. Each turns an already-guarded aggregate payload into raw model text.

  * `ClaudeProvider`       - the Anthropic API (production default when a key is set).
  * `HuggingFaceProvider`  - a small open model run locally with `transformers`. No API key, no
                             account, no network at inference time (the model is downloaded once
                             from the Hugging Face Hub), and the data never leaves the machine.

Providers receive only the payload that passed `src.narrative.guard`; they never see summaries
or rows. Every provider translates its own failures into `src.narrative.errors` types.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, Protocol

import anthropic

from config.settings import Settings
from src.narrative.errors import NarrativeConfigError, NarrativeGenerationError
from src.narrative.prompts import (
    LOCAL_SYSTEM_PROMPT,
    REPORT_SCHEMA,
    SYSTEM_PROMPT,
    build_local_user_prompt,
    build_user_prompt,
)

log = logging.getLogger(__name__)


class NarrativeProvider(Protocol):
    name: str

    def describe(self) -> str: ...

    def complete(self, payload: dict[str, Any], attempt: int) -> str:
        """Return the model's raw text for a guarded payload. `attempt` is 1-based."""
        ...


# ------------------------------------------------------------------------------------ Claude
CLAUDE_MAX_SDK_RETRIES = 3  # backoff on 429 / 5xx / timeouts / connection errors
CLAUDE_TIMEOUT_SECONDS = 60.0
CLAUDE_MAX_TOKENS = 2000


class ClaudeProvider:
    name = "claude"

    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None):
        self._settings = settings
        self._client = client  # injected in tests; otherwise built lazily so a missing key
        # only fails when a report is actually requested

    def describe(self) -> str:
        return f"Claude ({self._settings.model})"

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            key = self._settings.anthropic_api_key
            if not key:
                raise NarrativeConfigError(
                    "ANTHROPIC_API_KEY is not set. Set it in the environment (see config/.env.example), "
                    "or use the free local model with RETAIL_PULSE_NARRATIVE_PROVIDER=huggingface."
                )
            self._client = anthropic.Anthropic(
                api_key=key, max_retries=CLAUDE_MAX_SDK_RETRIES, timeout=CLAUDE_TIMEOUT_SECONDS
            )
        return self._client

    def complete(self, payload: dict[str, Any], attempt: int) -> str:
        client = self._get_client()
        try:
            response = client.messages.create(
                model=self._settings.model,
                max_tokens=CLAUDE_MAX_TOKENS,
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


# ------------------------------------------------------------------------- Hugging Face (local)
HF_MAX_NEW_TOKENS = 400

_pipelines: dict[str, Any] = {}  # loaded models are kept for the life of the process
_pipeline_lock = threading.Lock()


def _load_pipeline(model_id: str) -> Any:
    """Load (once) a local text-generation pipeline. Heavy imports happen here, not at import time."""
    with _pipeline_lock:
        if model_id in _pipelines:
            return _pipelines[model_id]
        try:
            from transformers import pipeline
        except ImportError as exc:
            raise NarrativeConfigError(
                "The local model needs the Hugging Face extras: pip install -e \".[hf]\""
            ) from exc
        log.info("Loading local model %s (first use downloads it from the Hugging Face Hub)...", model_id)
        try:
            _pipelines[model_id] = pipeline("text-generation", model=model_id, torch_dtype="auto")
        except MemoryError as exc:
            raise NarrativeGenerationError(
                f"Not enough memory to load {model_id!r}. Try a smaller model via RETAIL_PULSE_HF_MODEL "
                "(for example Qwen/Qwen2.5-0.5B-Instruct)."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - hub/network/model errors vary widely
            raise NarrativeGenerationError(f"Could not load the local model {model_id!r}: {exc}") from exc
        return _pipelines[model_id]


class HuggingFaceProvider:
    name = "huggingface"

    def __init__(self, model_id: str, pipeline_factory: Callable[[str], Any] | None = None):
        self._model_id = model_id
        self._pipeline_factory = pipeline_factory or _load_pipeline

    def describe(self) -> str:
        return f"Hugging Face, running locally ({self._model_id})"

    def complete(self, payload: dict[str, Any], attempt: int) -> str:
        pipe = self._pipeline_factory(self._model_id)
        messages = [
            {"role": "system", "content": LOCAL_SYSTEM_PROMPT},
            {"role": "user", "content": build_local_user_prompt(payload)},
        ]
        # First attempt is greedy (deterministic). A retry samples a little so it can differ.
        if attempt == 1:  # unset the model's default sampling knobs so greedy decoding is not warned about
            sampling = {"do_sample": False, "temperature": None, "top_p": None, "top_k": None}
        else:
            sampling = {"do_sample": True, "temperature": 0.3, "top_p": 0.9}
        try:
            out = pipe(messages, max_new_tokens=HF_MAX_NEW_TOKENS, return_full_text=False, **sampling)
        except MemoryError as exc:
            raise NarrativeGenerationError("Ran out of memory generating the report locally.") from exc
        except Exception as exc:  # noqa: BLE001
            raise NarrativeGenerationError(f"The local model failed while generating: {exc}") from exc
        return _generated_text(out)


def _generated_text(out: Any) -> str:
    """Pull the reply text out of a transformers pipeline result."""
    first = out[0] if isinstance(out, list) and out else out
    text = first.get("generated_text", "") if isinstance(first, dict) else first
    if isinstance(text, list):  # chat-style result: last message is the assistant reply
        text = text[-1].get("content", "") if text else ""
    return text if isinstance(text, str) else ""


# --------------------------------------------------------------------------------- selection
def create_provider(settings: Settings) -> NarrativeProvider:
    """Provider for the configured engine. Constructing one never loads a model or calls an API."""
    if settings.resolved_provider == "huggingface":
        return HuggingFaceProvider(settings.hf_model)
    return ClaudeProvider(settings)


def describe_provider(settings: Settings) -> str:
    """Human-readable name of the engine that would write the report (cheap; loads nothing)."""
    return create_provider(settings).describe()
