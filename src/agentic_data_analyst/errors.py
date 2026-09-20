"""Application exceptions safe to translate at transport boundaries."""


class AnalystError(Exception):
    """Base class for expected workflow failures."""


class CatalogError(AnalystError):
    """Catalog data is missing or malformed."""


class LLMError(AnalystError):
    """The model provider failed or returned an invalid response."""


class UnsafeAnalysisError(AnalystError):
    """An analysis did not pass validation."""


class ExecutionError(AnalystError):
    """Spark could not execute an otherwise valid analysis."""
