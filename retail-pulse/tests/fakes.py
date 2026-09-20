"""Test doubles for the Claude API. No network, no API key, no cost."""

from __future__ import annotations

import json
import types
from collections.abc import Callable
from typing import Any

import httpx2 as httpx

PAYLOAD_HEADER = "Weekly retail metrics (JSON):\n"


def text_response(text: str, stop_reason: str = "end_turn") -> types.SimpleNamespace:
    return types.SimpleNamespace(stop_reason=stop_reason,
                                 content=[types.SimpleNamespace(type="text", text=text)])  # fmt: skip


def report_json(headline="Headline", cause="Cause.", actions=("one", "two", "three")) -> str:
    return json.dumps({"headline": headline, "likely_cause": cause, "recommended_actions": list(actions)})


def api_error(cls, status: int):
    """Build an `anthropic` API exception the way the SDK would raise it."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=request), body=None)


class FakeClaude:
    """Stands in for `anthropic.Anthropic`. Records every request in `.calls`.

    Give it scripted outputs (responses or exceptions, consumed in order) or a `responder`
    callable that builds the reply from the request kwargs.
    """

    def __init__(self, *outputs: Any, responder: Callable[[dict], Any] | None = None):
        self._outputs = list(outputs)
        self._responder = responder
        self.calls: list[dict] = []
        self.messages = self  # client.messages.create(...)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        out = self._responder(kwargs) if self._responder else self._outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    # ---- helpers for assertions ---------------------------------------------------
    @property
    def sent_payload(self) -> dict:
        """The JSON payload embedded in the (last) user prompt."""
        content = self.calls[-1]["messages"][0]["content"]
        return json.loads(content.removeprefix(PAYLOAD_HEADER))

    @property
    def sent_text(self) -> str:
        return self.calls[-1]["system"] + self.calls[-1]["messages"][0]["content"]
