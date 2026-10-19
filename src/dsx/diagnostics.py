"""Diagnostik terstruktur: setiap masalah memiliki kode, lokasi, dan pesan."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class Location:
    file: str
    line: int
    column: int = 1

    def __str__(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    code: str
    message: str
    location: Location | None = None
    details: tuple[tuple[str, str], ...] = ()

    def format(self) -> str:
        lines = [f"{self.severity.value}: {self.code}"]
        if self.location is not None:
            lines.append(f"Location: {self.location}")
        lines.append(f"Message: {self.message}")
        for key, value in self.details:
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        loc = None
        if self.location is not None:
            loc = {
                "file": self.location.file,
                "line": self.location.line,
                "column": self.location.column,
            }
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "location": loc,
            "details": {k: v for k, v in self.details},
        }


class DsxSyntaxError(Exception):
    """Kesalahan sintaks. Parsing berhenti pada kesalahan pertama."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


class FatalDsxError(Exception):
    """Kesalahan yang menghentikan seluruh proses (mis. batas sumber daya)."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def make_details(**details: Any) -> tuple[tuple[str, str], ...]:
    return tuple(
        (key.replace("_", " ").capitalize(), str(value))
        for key, value in details.items()
        if value is not None
    )


class DiagnosticBag:
    """Kumpulan diagnostik dengan batas jumlah agar tidak membanjiri keluaran."""

    def __init__(self, max_items: int = 500) -> None:
        self._items: list[Diagnostic] = []
        self._max = max_items
        self._errors = 0
        self._dropped = 0

    def add(
        self,
        severity: Severity,
        code: str,
        message: str,
        location: Location | None = None,
        **details: Any,
    ) -> None:
        if severity is Severity.ERROR:
            self._errors += 1
        if len(self._items) >= self._max:
            self._dropped += 1
            return
        self._items.append(
            Diagnostic(severity, code, message, location, make_details(**details))
        )

    def add_diagnostic(self, diagnostic: Diagnostic) -> None:
        if diagnostic.severity is Severity.ERROR:
            self._errors += 1
        if len(self._items) >= self._max:
            self._dropped += 1
            return
        self._items.append(diagnostic)

    def error(self, code: str, message: str, location: Location | None = None, **details: Any) -> None:
        self.add(Severity.ERROR, code, message, location, **details)

    def warning(self, code: str, message: str, location: Location | None = None, **details: Any) -> None:
        self.add(Severity.WARNING, code, message, location, **details)

    @property
    def has_errors(self) -> bool:
        return self._errors > 0

    @property
    def items(self) -> list[Diagnostic]:
        items = list(self._items)
        if self._dropped:
            items.append(
                Diagnostic(
                    Severity.WARNING,
                    "DIAGNOSTICS_TRUNCATED",
                    f"{self._dropped} diagnostik tambahan tidak ditampilkan.",
                )
            )
        return items

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self._items if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity is Severity.WARNING]
