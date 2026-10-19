"""DocScript AI (DSX): bahasa deklaratif untuk menyusun dokumen terstruktur."""

from __future__ import annotations

LANGUAGE_VERSION = "2.4"
__version__ = "0.4.0"

from .api.service import (  # noqa: E402
    GenerationResult,
    check_document,
    generate_document,
    generate_from_directory,
)
from .diagnostics import Diagnostic, Location, Severity  # noqa: E402
from .limits import Limits  # noqa: E402

__all__ = [
    "LANGUAGE_VERSION",
    "__version__",
    "Diagnostic",
    "GenerationResult",
    "Limits",
    "Location",
    "Severity",
    "check_document",
    "generate_document",
    "generate_from_directory",
]
