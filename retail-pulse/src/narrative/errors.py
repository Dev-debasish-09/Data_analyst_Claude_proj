"""Exceptions raised by the narrative layer."""


class NarrativeError(Exception):
    """Base class for all narrative-layer failures."""


class RawDataBoundaryError(NarrativeError, ValueError):
    """Something other than a pre-aggregated summary was passed toward the Claude API.

    This is the data-boundary guard: row-level data (household lists, basket rows, DataFrames)
    must never reach the API. Raised BEFORE any network call is made.
    """


class NarrativeConfigError(NarrativeError):
    """The narrative layer is not configured (e.g. ANTHROPIC_API_KEY is not set)."""


class NarrativeGenerationError(NarrativeError):
    """The API call failed after retries, was refused, or returned an unusable report."""
