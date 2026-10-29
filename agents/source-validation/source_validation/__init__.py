"""source-validation: Independent source & intent verification for lunch scrapers."""
from .config import ValidationConfig
from .errors import ValidationError
from .models import CheckResult, Diagnosis, DishEvidence, ValidationResult, Verdict
from .skill import validate_sources
from .validator import validate_candidate

__all__ = [
    "ValidationConfig",
    "ValidationError",
    "CheckResult",
    "Diagnosis",
    "DishEvidence",
    "ValidationResult",
    "Verdict",
    "validate_sources",
    "validate_candidate",
]
