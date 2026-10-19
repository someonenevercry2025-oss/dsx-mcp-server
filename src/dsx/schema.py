"""Skema komponen dan properti DSX.

Satuan (Blueprint IV/VII.3):
- size, space_before, space_after : point (pt)
- indent_*, margin, width, height : sentimeter (cm)
- line                            : pengali jarak baris (1.0 = tunggal)
"""

from __future__ import annotations

from dataclasses import dataclass

ROLES = ("body", "heading", "title", "subtitle", "caption", "quote", "note", "warning", "code", "callout")
CALLOUT_TYPES = ("info", "note", "warning", "tip", "important")
ALIGNS = ("left", "center", "right", "justify")
BLOCK_ALIGNS = ("left", "center", "right")
PAGE_SIZES = {
    "A3": (29.7, 42.0),
    "A4": (21.0, 29.7),
    "A5": (14.8, 21.0),
    "Letter": (21.59, 27.94),
    "Legal": (21.59, 35.56),
}
VISUAL_KEYS = (
    "font",
    "size",
    "bold",
    "italic",
    "underline",
    "color",
    "align",
    "line",
    "space_before",
    "space_after",
    "indent_left",
    "indent_right",
    "indent_first",
    "page_break_before",
)
SUPPORTED_VERSIONS = ("2.1", "2.2", "2.3", "2.4")


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str
    required: bool = False
    positional: bool = False
    choices: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None
    step: float | None = None
    code: str | None = None
    max_len: int | None = None
    unit: str | None = None  # satuan dasar bila param menerima angka bersatuan: pt | cm


@dataclass(frozen=True)
class Spec:
    name: str
    category: str  # meta | styledef | content | value
    params: tuple[ParamSpec, ...]
    visual: bool = False

    def all_params(self) -> dict[str, ParamSpec]:
        merged: dict[str, ParamSpec] = {}
        if self.visual:
            merged.update({p.name: p for p in VISUAL_PARAMS})
        merged.update({p.name: p for p in self.params})
        return merged


def _p(name: str, type_: str, **kw: object) -> ParamSpec:
    return ParamSpec(name, type_, **kw)  # type: ignore[arg-type]


# Nama alternatif (selaras dengan istilah paragraf umum) -> nama kanonik.
ALIASES = {
    "first_line_indent": "indent_first",
    "left_indent": "indent_left",
    "right_indent": "indent_right",
    "line_spacing": "line",
    "alignment": "align",
}

VISUAL_PARAMS: tuple[ParamSpec, ...] = (
    _p("font", "font"),
    _p("size", "num", min=1, max=400, step=0.5, unit="pt"),
    _p("bold", "bool"),
    _p("italic", "bool"),
    _p("underline", "bool"),
    _p("color", "color"),
    _p("align", "enum_ci", choices=ALIGNS),
    _p("line", "num", min=0.5, max=10),
    _p("space_before", "num", min=0, max=1000, unit="pt"),
    _p("space_after", "num", min=0, max=1000, unit="pt"),
    _p("indent_left", "num", min=-50, max=50, unit="cm"),
    _p("indent_right", "num", min=-50, max=50, unit="cm"),
    _p("indent_first", "num", min=-50, max=50, unit="cm"),
    _p("hanging_indent", "num", min=0, max=50, unit="cm"),  # diterjemahkan menjadi indent_first negatif
    _p("page_break_before", "bool"),
)

SPECS: dict[str, Spec] = {}


def _add(name: str, category: str, params: list[ParamSpec], visual: bool = False) -> None:
    SPECS[name] = Spec(name, category, tuple(params), visual)


_MARGIN = dict(min=0, max=10, unit="cm")

_add("DSX", "meta", [_p("version", "str", max_len=20)])
_add(
    "DOC",
    "meta",
    [
        _p("title", "str", max_len=1000),
        _p("template", "str", max_len=100),
        _p("author", "str", max_len=1000),
        _p("subject", "str", max_len=1000),
        _p("language", "str", max_len=35),
    ],
)
_add(
    "PAGE",
    "meta",
    [
        _p("size", "enum", choices=tuple(PAGE_SIZES)),
        _p("orientation", "enum", choices=("portrait", "landscape")),
        _p("margin", "num", **_MARGIN),
        _p("margin_top", "num", **_MARGIN),
        _p("margin_bottom", "num", **_MARGIN),
        _p("margin_left", "num", **_MARGIN),
        _p("margin_right", "num", **_MARGIN),
    ],
)
_add("STYLE", "meta", [], visual=True)
_add(
    "STYLEDEF",
    "styledef",
    [
        _p("name", "name", required=True, positional=True),
        _p("extends", "str", max_len=64),
        _p("role", "enum", choices=ROLES),
        _p("level", "int", min=1, max=9, code="INVALID_HEADING_LEVEL"),
    ],
    visual=True,
)
_add("HEADER", "meta", [_p("text", "str", required=True, positional=True, max_len=2000), _p("style", "str", max_len=64)], visual=True)
_add("FOOTER", "meta", [_p("text", "str", required=True, positional=True, max_len=2000), _p("style", "str", max_len=64)], visual=True)
_add(
    "PAGENUM",
    "meta",
    [
        _p("position", "enum", choices=("header", "footer")),
        _p("format", "str", max_len=200),
        _p("style", "str", max_len=64),
    ],
    visual=True,
)

_TEXT_STYLE = [_p("style", "str", max_len=64)]
_add(
    "TEXT",
    "content",
    [
        _p("text", "richtext", required=True, positional=True),
        _p("role", "enum", choices=ROLES),
        _p("level", "int", min=1, max=9, code="INVALID_HEADING_LEVEL"),
        *_TEXT_STYLE,
    ],
    visual=True,
)
_add("P", "content", [_p("text", "richtext", required=True, positional=True), *_TEXT_STYLE], visual=True)
for _n in range(1, 10):
    _add(f"H{_n}", "content", [_p("text", "richtext", required=True, positional=True), *_TEXT_STYLE], visual=True)
_add(
    "TEXTBLOCK",
    "content",
    [
        _p("text", "text", required=True, positional=True),
        _p("role", "enum", choices=ROLES),
        _p("level", "int", min=1, max=9, code="INVALID_HEADING_LEVEL"),
        *_TEXT_STYLE,
    ],
    visual=True,
)
_add(
    "FIGURE",
    "content",
    [
        _p("src", "image", required=True),
        _p("caption", "str", max_len=5000),
        _p("width", "num", min=0.1, max=100, unit="cm"),
        _p("height", "num", min=0.1, max=100, unit="cm"),
        _p("align", "enum_ci", choices=BLOCK_ALIGNS),
        _p("alt", "str", max_len=2000),
        _p("caption_style", "str", max_len=64),
    ],
)
_add(
    "TABLE",
    "content",
    [
        _p("headers", "strlist"),
        _p("rows", "rows"),
        _p("data", "csv"),
        _p("header", "bool"),
        _p("caption", "str", max_len=5000),
        _p("align", "enum_ci", choices=BLOCK_ALIGNS),
        _p("caption_style", "str", max_len=64),
    ],
)
_add("PAGEBREAK", "content", [])
_add(
    "CALLOUT",
    "content",
    [
        _p("text", "richtext", required=True, positional=True),
        _p("type", "enum_ci", choices=CALLOUT_TYPES),
        _p("title", "str", max_len=500),
        *_TEXT_STYLE,
    ],
    visual=True,
)
_add(
    "LIST",
    "content",
    [
        _p("items", "items", required=True, positional=True),
        _p("ordered", "bool"),
        _p("start", "int", min=1, max=100000),
        _p("indent", "num", min=0.25, max=5, unit="cm"),
        _p("hanging", "num", min=0.1, max=3, unit="cm"),
        *_TEXT_STYLE,
    ],
    visual=True,
)
_add(
    "BULLET",
    "content",
    [
        _p("items", "items", required=True, positional=True),
        _p("indent", "num", min=0.25, max=5, unit="cm"),
        _p("hanging", "num", min=0.1, max=3, unit="cm"),
        *_TEXT_STYLE,
    ],
    visual=True,
)
_add(
    "MATH",
    "content",
    [
        _p("expr", "math", required=True, positional=True),
        _p("align", "enum_ci", choices=BLOCK_ALIGNS),
        _p("size", "num", min=6, max=72, step=0.5, unit="pt"),
    ],
)

_add("FILE", "value", [_p("path", "str", required=True, positional=True)])
_add("IMAGE", "value", [_p("path", "str", required=True, positional=True)])
_add("IMATH", "value", [_p("expr", "math", required=True, positional=True)])
_add("CSV", "value", [_p("path", "str", required=True, positional=True), _p("delimiter", "str", max_len=1)])
_add("BOLD", "value", [_p("text", "str", required=True, positional=True, max_len=5000)])
_add("ITALIC", "value", [_p("text", "str", required=True, positional=True, max_len=5000)])
_add("UNDERLINE", "value", [_p("text", "str", required=True, positional=True, max_len=5000)])
_add(
    "LINK",
    "value",
    [
        _p("text", "str", required=True, positional=True, max_len=2000),
        _p("url", "str", required=True, max_len=2000),
    ],
)
_add("FOOTNOTE", "value", [_p("text", "str", required=True, positional=True, max_len=5000)])
_add(
    "TOC",
    "content",
    [
        _p("title", "str", max_len=200),
        _p("depth", "int", min=1, max=9),
    ],
)

VALUE_FUNCTIONS = (
    "FILE",
    "IMAGE",
    "CSV",
    "IMATH",
    "BOLD",
    "ITALIC",
    "UNDERLINE",
    "LINK",
    "FOOTNOTE",
)
RESERVED_NAMES = frozenset({"LET", "true", "false"} | set(SPECS))
