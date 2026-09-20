"""The report produced by the narrative layer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NarrativeReport:
    headline: str
    likely_cause: str
    recommended_actions: tuple[str, str, str]
