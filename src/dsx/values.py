"""Tipe nilai DSX hasil evaluasi ekspresi."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


class _Invalid:
    """Sentinel: ekspresi gagal dievaluasi dan kesalahannya sudah dilaporkan."""

    _instance: "_Invalid | None" = None

    def __new__(cls) -> "_Invalid":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<invalid>"

    def __bool__(self) -> bool:
        return False


INVALID = _Invalid()


@dataclass(frozen=True)
class Length:
    """Angka bersatuan (cm, pt, in), mis. ``1.25cm``."""

    value: float
    unit: str


@dataclass(frozen=True)
class TextRef:
    path: str


@dataclass(frozen=True)
class ImageRef:
    path: str


@dataclass(frozen=True)
class CsvRef:
    path: str
    delimiter: str = ","


@dataclass(frozen=True)
class StyledText:
    """Teks dengan format sebaris (bold/italic/underline)."""

    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass(frozen=True)
class LinkValue:
    """Hyperlink sebaris."""

    text: str
    url: str
    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass(frozen=True)
class FootnoteValue:
    """Referensi catatan kaki (teks catatan disimpan di value)."""

    text: str


Value = Union[
    str,
    int,
    float,
    bool,
    list,
    TextRef,
    ImageRef,
    CsvRef,
    StyledText,
    LinkValue,
    FootnoteValue,
]


def type_name(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "bilangan bulat"
    if isinstance(value, float):
        return "angka desimal"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, TextRef):
        return "referensi file teks"
    if isinstance(value, ImageRef):
        return "referensi gambar"
    if isinstance(value, CsvRef):
        return "referensi CSV"
    if isinstance(value, Length):
        return "ukuran bersatuan"
    if isinstance(value, StyledText):
        return "teks berformat"
    if isinstance(value, LinkValue):
        return "hyperlink"
    if isinstance(value, FootnoteValue):
        return "catatan kaki"
    if type(value).__name__ == "ParsedMath":
        return "ekspresi matematika (IMATH)"
    return type(value).__name__
