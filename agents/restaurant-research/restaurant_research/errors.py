"""Exception types for the restaurant-research Skill."""


class ResearchError(Exception):
    """Base error for the restaurant-research Skill."""


class FetcherNotConfiguredError(ResearchError):
    """Raised when no web fetcher is configured and mock is not allowed."""
