"""Template: konfigurasi lapisan kedua (setelah default engine)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Template:
    name: str
    normal: dict[str, Any] = field(default_factory=dict)
    styles: dict[str, dict[str, Any]] = field(default_factory=dict)
    page: dict[str, Any] = field(default_factory=dict)


_HEADING_COLOR = "#1F3864"

TEMPLATES: dict[str, Template] = {
    "default": Template("default"),
    "academic-paper": Template(
        "academic-paper",
        normal={"font": "Times New Roman", "size": 12, "line": 1.5, "align": "justify", "space_after": 6},
        styles={
            "title": {"size": 16, "space_after": 18},
            "heading-1": {"size": 14, "align": "center", "space_before": 12, "space_after": 12},
            "heading-2": {"size": 12, "space_before": 12, "space_after": 6},
            "heading-3": {"size": 12, "italic": True, "space_before": 12, "space_after": 6},
            "heading-4": {"size": 12},
            "heading-5": {"size": 12},
            "heading-6": {"size": 12},
            "heading-7": {"size": 12},
            "heading-8": {"size": 12},
            "heading-9": {"size": 12},
            "caption": {"size": 10},
            "quote": {"line": 1.0, "indent_left": 1.25, "indent_right": 0, "align": "justify"},
        },
        page={"size": "A4", "margin_top": 3, "margin_left": 4, "margin_right": 3, "margin_bottom": 3},
    ),
    "project-report": Template(
        "project-report",
        normal={"font": "Arial", "size": 11, "line": 1.15, "align": "left", "space_after": 8},
        styles={
            **{f"heading-{n}": {"color": _HEADING_COLOR} for n in range(1, 10)},
            "title": {"color": _HEADING_COLOR},
        },
        page={"size": "A4", "margin_top": 2.5, "margin_bottom": 2.5, "margin_left": 2.5, "margin_right": 2.5},
    ),
}


def get_template(name: str) -> Template | None:
    return TEMPLATES.get(name)
