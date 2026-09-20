"""Data-boundary guard: only pre-aggregated summaries may reach the Claude API.

Two independent layers, both enforced before any network call:

  1. TYPE allowlist (`to_payload`): the only accepted inputs are the summary dataclasses
     produced by `src.analysis`. DataFrames, raw dicts, lists of records and everything else
     are rejected outright.
  2. SHAPE check (`assert_aggregated_only`): even a legitimate summary object is inspected
     after conversion to a plain dict, so a future change that smuggles row-level data into a
     summary is still caught. It rejects identifier-like keys, long lists (a household_id-level
     list is the canonical example), non-JSON types (DataFrames, numpy arrays), excessive
     nesting, and oversized payloads.

The limits are deliberately tight: today's summaries hold at most a few dozen items per list.
If a legitimate summary needs more, raise the limit here on purpose, not by accident.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from src.analysis import as_dict
from src.analysis.models import (
    PromoLiftSummary,
    SegmentBehaviorSummary,
    StockoutSummary,
    WeeklySalesChangeSummary,
)
from src.narrative.errors import RawDataBoundaryError

ALLOWED_SUMMARY_TYPES: tuple[type, ...] = (
    WeeklySalesChangeSummary,
    StockoutSummary,
    PromoLiftSummary,
    SegmentBehaviorSummary,
)

MAX_RECORD_LIST_ITEMS = 25  # lists of dicts/lists (would be row-like)
MAX_SCALAR_LIST_ITEMS = 10  # lists of numbers/strings (would be ID-like)
MAX_DEPTH = 6
MAX_PAYLOAD_CHARS = 30_000
_JSON_SCALARS = (str, int, float, bool, type(None))

# A key that identifies a row or person: "household_id", "basket_id", "store_ids", "id", ...
# Product codes (`upc`) and counts (`n_households`) do not match and stay allowed.
_IDENTIFIER_KEY = re.compile(r"(^|_)ids?$", re.IGNORECASE)
_ROW_LEVEL_KEY = re.compile(
    r"household|customer|shopper|loyalty|card_?number|trans_?time|transaction|basket_?(id|value_?list)",
    re.IGNORECASE,
)
_ALLOWED_COUNT_KEY = re.compile(r"^(n|num|count)_", re.IGNORECASE)  # n_households, n_baskets, ...


def to_payload(summaries: Any) -> dict[str, Any]:
    """Convert analysis summaries into the plain-dict payload, enforcing the boundary.

    Accepts one summary or a sequence of summaries (one per metric). Returns
    `{"<SummaryClassName>": {...}}`. Raises `RawDataBoundaryError` for anything else.
    """
    items: Sequence[Any] = summaries if isinstance(summaries, (list, tuple)) else (summaries,)
    if not items:
        raise RawDataBoundaryError("No summaries provided.")

    payload: dict[str, Any] = {}
    for item in items:
        if not isinstance(item, ALLOWED_SUMMARY_TYPES):
            allowed = ", ".join(t.__name__ for t in ALLOWED_SUMMARY_TYPES)
            raise RawDataBoundaryError(
                f"Only pre-aggregated analysis summaries may be sent to the API "
                f"(allowed: {allowed}); got {type(item).__name__}."
            )
        name = type(item).__name__
        if name in payload:
            raise RawDataBoundaryError(f"Duplicate summary type {name} in one report.")
        payload[name] = as_dict(item)

    assert_aggregated_only(payload)
    return payload


def assert_aggregated_only(payload: Any) -> None:
    """Raise `RawDataBoundaryError` if `payload` looks like it contains row-level data."""
    _walk(payload, path="payload", depth=0)
    size = len(json.dumps(payload, default=str))
    if size > MAX_PAYLOAD_CHARS:
        raise RawDataBoundaryError(
            f"Payload is {size:,} characters (limit {MAX_PAYLOAD_CHARS:,}); "
            "this is too large to be a pre-aggregated summary."
        )


def _walk(node: Any, path: str, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise RawDataBoundaryError(f"{path}: nesting deeper than {MAX_DEPTH} levels.")

    if isinstance(node, dict):
        for key, value in node.items():
            if not isinstance(key, str):
                raise RawDataBoundaryError(f"{path}: non-string key {key!r}.")
            if _is_row_level_key(key):
                raise RawDataBoundaryError(
                    f"{path}.{key}: key looks like a row-level identifier; "
                    "only aggregated figures may be sent."
                )
            _walk(value, f"{path}.{key}", depth + 1)
    elif isinstance(node, (list, tuple)):
        is_scalar_list = all(isinstance(x, _JSON_SCALARS) for x in node)
        limit = MAX_SCALAR_LIST_ITEMS if is_scalar_list else MAX_RECORD_LIST_ITEMS
        if len(node) > limit:
            raise RawDataBoundaryError(
                f"{path}: list of {len(node)} items exceeds the limit of {limit}; "
                "looks like a record-level list, not an aggregate."
            )
        for i, value in enumerate(node):
            _walk(value, f"{path}[{i}]", depth + 1)
    elif not isinstance(node, _JSON_SCALARS):
        raise RawDataBoundaryError(
            f"{path}: {type(node).__name__} is not a plain aggregate value "
            "(DataFrames, arrays and custom objects are rejected)."
        )


def _is_row_level_key(key: str) -> bool:
    if _ALLOWED_COUNT_KEY.match(key):
        return False
    return bool(_IDENTIFIER_KEY.search(key) or _ROW_LEVEL_KEY.search(key))
