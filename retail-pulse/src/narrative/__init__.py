"""Narrative layer: turns aggregated analysis summaries into a plain-English report via Claude."""

from src.narrative.errors import (
    NarrativeConfigError,
    NarrativeError,
    NarrativeGenerationError,
    RawDataBoundaryError,
)
from src.narrative.generator import NarrativeGenerator
from src.narrative.guard import assert_aggregated_only, to_payload
from src.narrative.models import NarrativeReport

__all__ = [
    "NarrativeConfigError",
    "NarrativeError",
    "NarrativeGenerationError",
    "NarrativeGenerator",
    "NarrativeReport",
    "RawDataBoundaryError",
    "assert_aggregated_only",
    "to_payload",
]
