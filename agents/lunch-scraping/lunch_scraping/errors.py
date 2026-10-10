"""Exception types for the lunch-scraping Skill."""


class ScrapingError(Exception):
    """Base error for the lunch-scraping Skill."""


class BrowserUnavailableError(ScrapingError):
    """Raised when a browser/Playwright engine is required but not installed."""


class ConfigurationError(ScrapingError):
    """Raised when a scraper configuration is invalid or incomplete."""
