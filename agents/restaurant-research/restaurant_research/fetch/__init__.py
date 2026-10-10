"""Web fetching abstraction for restaurant-research.

The WebFetcher is the second component in the pipeline: it turns a URL into
fetched page content (text + links + type) that the evaluator can reason about.
It is swappable (HTTP vs mock) and mockable so tests never hit the network.
"""
from .base import WebFetcher, FetchedPage
from .http import HttpWebFetcher
from .mock import MockWebFetcher
from .factory import create_fetcher

__all__ = [
    "WebFetcher",
    "FetchedPage",
    "HttpWebFetcher",
    "MockWebFetcher",
    "create_fetcher",
]
