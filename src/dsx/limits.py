"""Batas sumber daya engine (Blueprint X.2)."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .diagnostics import Diagnostic, FatalDsxError, Severity


@dataclass(frozen=True)
class Limits:
    max_dsx_bytes: int = 1_000_000
    max_tokens: int = 500_000
    max_nesting_depth: int = 32
    max_variable_depth: int = 100
    max_content_bytes: int = 5_000_000
    max_csv_bytes: int = 5_000_000
    max_image_bytes: int = 20_000_000
    max_image_pixels: int = 100_000_000
    max_total_bytes: int = 100_000_000
    max_referenced_files: int = 500
    max_components: int = 50_000
    max_paragraphs: int = 200_000
    max_table_rows: int = 10_000
    max_table_columns: int = 63
    max_table_cells: int = 200_000
    max_cell_chars: int = 10_000
    max_diagnostics: int = 500
    max_list_items: int = 10_000
    max_list_depth: int = 9
    max_math_chars: int = 2_000
    max_math_nodes: int = 5_000
    max_math_depth: int = 30
    max_callout_paragraphs: int = 1_000
    max_inline_segments: int = 10_000
    max_render_seconds: float = 60.0


class Deadline:
    """Batas waktu kooperatif untuk kompilasi dan rendering."""

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds
        self._end = time.monotonic() + seconds

    def check(self) -> None:
        if time.monotonic() > self._end:
            raise FatalDsxError(
                Diagnostic(
                    Severity.ERROR,
                    "TIMEOUT",
                    f"Pemrosesan melebihi batas waktu {self._seconds:g} detik.",
                )
            )
