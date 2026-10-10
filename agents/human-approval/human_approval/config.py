"""Configuration for the human-approval Skill."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ApprovalConfig:
    """Runtime configuration for the human-approval Skill.

    Attributes
    ----------
    db_path:
        Self-contained SQLite path. Needed to persist the queue and decisions
        (so a decision recorded later is reflected in the queue). ``None`` keeps
        everything in-memory for a single call.
    """

    db_path: Optional[str] = None

    @classmethod
    def from_env(cls, **overrides) -> "ApprovalConfig":
        cfg = cls(db_path=os.environ.get("HA_DB_PATH"))
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg
