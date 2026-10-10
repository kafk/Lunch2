"""Exception types for the restaurant-discovery Skill."""


class DiscoveryError(Exception):
    """Base error for the restaurant-discovery Skill."""


class ProviderNotConfiguredError(DiscoveryError):
    """Raised when no web-search provider is configured and mock is not allowed."""
