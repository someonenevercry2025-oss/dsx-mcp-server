"""Default engine: nilai dasar dan style bawaan DSX."""

from __future__ import annotations

from typing import Any

ENGINE_BASE: dict[str, Any] = {
    "font": "Calibri",
    "size": 11,
    "bold": False,
    "italic": False,
    "underline": False,
    "color": "#000000",
    "align": "left",
    "line": 1.15,
    "space_before": 0,
    "space_after": 6,
    "indent_left": 0,
    "indent_right": 0,
    "indent_first": 0,
    "page_break_before": False,
}

_HEADING_SIZES = {1: 20, 2: 16, 3: 14, 4: 12, 5: 11, 6: 11, 7: 11, 8: 10, 9: 10}
_HEADING_ITALIC = {6, 7, 8, 9}
_HEADING_BOLD = {1, 2, 3, 4, 5, 6, 8}


def _heading_props(level: int) -> dict[str, Any]:
    return {
        "size": _HEADING_SIZES[level],
        "bold": level in _HEADING_BOLD,
        "italic": level in _HEADING_ITALIC,
        "align": "left",
        "indent_first": 0,
        "space_before": 12 if level <= 3 else 10,
        "space_after": 6,
    }


# (nama, role, level, parent, properti)
BUILTIN_STYLES: list[tuple[str, str, int | None, str | None, dict[str, Any]]] = [
    ("normal", "body", None, None, {}),
    ("title", "title", None, "normal", {"size": 26, "bold": True, "align": "center", "indent_first": 0, "space_after": 12}),
    ("subtitle", "subtitle", None, "normal", {"size": 14, "italic": True, "color": "#595959", "align": "center", "indent_first": 0, "space_after": 12}),
    *[(f"heading-{n}", "heading", n, "normal", _heading_props(n)) for n in range(1, 10)],
    ("quote", "quote", None, "normal", {"italic": True, "indent_left": 1, "indent_right": 1, "indent_first": 0}),
    ("caption", "caption", None, "normal", {"size": 9, "italic": True, "align": "center", "indent_first": 0}),
    ("note", "note", None, "normal", {"italic": True, "color": "#444444", "indent_left": 0.5, "indent_first": 0}),
    ("warning", "warning", None, "normal", {"bold": True, "color": "#9C0006", "indent_first": 0}),
    ("code", "code", None, "normal", {"font": "Courier New", "size": 10, "line": 1.0, "align": "left", "indent_first": 0}),
    ("list-item", "body", None, "normal", {"indent_first": 0, "indent_left": 0, "space_after": 3, "align": "left"}),
    ("equation", "body", None, "normal", {"align": "center", "indent_first": 0, "indent_left": 0, "line": 1.0, "space_before": 6, "space_after": 6}),
    ("callout-title", "callout", None, "normal", {"bold": True, "indent_first": 0, "indent_left": 0, "align": "left", "line": 1.0, "space_before": 0, "space_after": 3}),
    *[
        (f"callout-{kind}", "callout", None, "normal", {"indent_first": 0, "indent_left": 0, "align": "left", "line": 1.0, "space_before": 0, "space_after": 4})
        for kind in ("info", "note", "warning", "tip", "important")
    ],
]

# Tema visual callout (dipakai renderer): warna isi, garis tepi kiri, dan warna judul.
CALLOUT_THEMES: dict[str, dict[str, str]] = {
    "info": {"fill": "DDEBF7", "border": "2E75B6", "title": "#1F4E79"},
    "note": {"fill": "F2F2F2", "border": "7F7F7F", "title": "#404040"},
    "warning": {"fill": "FFF2CC", "border": "BF9000", "title": "#7F6000"},
    "tip": {"fill": "E2EFDA", "border": "548235", "title": "#375623"},
    "important": {"fill": "FCE4D6", "border": "C00000", "title": "#9C0006"},
}

ROLE_DEFAULT_STYLE = {
    "body": "normal",
    "title": "title",
    "subtitle": "subtitle",
    "caption": "caption",
    "quote": "quote",
    "note": "note",
    "warning": "warning",
    "code": "code",
    "callout": "callout-note",
}
