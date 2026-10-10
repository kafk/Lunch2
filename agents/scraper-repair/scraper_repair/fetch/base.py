"""Base types for fetch backends (raw HTML for analysis)."""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Optional


@dataclass
class FetchedPage:
    url: str
    ok: bool = False
    final_url: Optional[str] = None
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    html: str = ""          # raw HTML for selector analysis
    error: Optional[str] = None


class Fetcher(abc.ABC):
    name: str = "unknown"

    @abc.abstractmethod
    def fetch(self, url: str, timeout: int = 15) -> FetchedPage:
        """Fetch ``url``. Must NOT raise on network errors; return ok=False."""
        raise NotImplementedError
