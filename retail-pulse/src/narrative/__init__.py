"""Narrative layer: turns aggregated analysis summaries into a plain-English report.

The engine is pluggable (Claude API, or a free local Hugging Face model); the data-boundary guard
sits in front of all of them."""

from src.narrative.errors import (
    NarrativeConfigError,
    NarrativeError,
    NarrativeGenerationError,
    RawDataBoundaryError,
)
from src.narrative.generator import NarrativeGenerator
from src.narrative.guard import assert_aggregated_only, to_payload
from src.narrative.models import NarrativeReport
from src.narrative.providers import (
    ClaudeProvider,
    HuggingFaceProvider,
    NarrativeProvider,
    create_provider,
    describe_provider,
)

__all__ = [
    "ClaudeProvider",
    "HuggingFaceProvider",
    "NarrativeConfigError",
    "NarrativeError",
    "NarrativeGenerationError",
    "NarrativeGenerator",
    "NarrativeProvider",
    "NarrativeReport",
    "RawDataBoundaryError",
    "assert_aggregated_only",
    "create_provider",
    "describe_provider",
    "to_payload",
]
