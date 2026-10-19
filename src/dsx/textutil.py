"""Utilitas teks: validasi karakter XML dan normalisasi baris."""

from __future__ import annotations

import re

_ILLEGAL_XML = re.compile("[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")
_SPACES = re.compile(r"[ \t\f\v]+")


def find_illegal_xml_char(text: str) -> int | None:
    match = _ILLEGAL_XML.search(text)
    return match.start() if match else None


def describe_char(char: str) -> str:
    return f"U+{ord(char):04X}"


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def collapse_spaces(text: str) -> str:
    """Ubah rangkaian spasi/tab menjadi satu spasi lalu pangkas ujungnya.

    NBSP (U+00A0) sengaja dipertahankan karena merupakan pilihan penulis.
    """
    return _SPACES.sub(" ", text).strip(" ")
