"""Exception types for the scraper-generation Skill."""


class GenerationError(Exception):
    """Base error for the scraper-generation Skill."""


class FetcherNotConfiguredError(GenerationError):
    """Raised when no web fetcher is configured and mock is not allowed."""
