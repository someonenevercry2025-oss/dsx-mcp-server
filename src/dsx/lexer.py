"""Lexical analysis DSX.

Tidak memakai eval() atau pemisahan berbasis baris; seluruh sumber dipindai
karakter demi karakter menjadi token.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass

from .diagnostics import Diagnostic, DsxSyntaxError, FatalDsxError, Location, Severity, make_details
from .limits import Limits
from .textutil import describe_char, find_illegal_xml_char, normalize_newlines


@dataclass(frozen=True)
class Token:
    kind: str
    value: object
    loc: Location


_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t"}
_NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
_UNIT = re.compile(r"(cm|pt|in)(?![A-Za-z0-9_])")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_PUNCT = {
    "(": "LPAREN",
    ")": "RPAREN",
    "[": "LBRACKET",
    "]": "RBRACKET",
    ",": "COMMA",
    "=": "EQUALS",
}
_TRAILING_INDENT = re.compile(r"\n[ \t]*$")


def _error(code: str, message: str, loc: Location, **details: object) -> DsxSyntaxError:
    return DsxSyntaxError(Diagnostic(Severity.ERROR, code, message, loc, make_details(**details)))


def _unescape(raw: str, loc: Location) -> str:
    out: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == "\\":
            if i + 1 >= n:
                raise _error("INVALID_ESCAPE", "Escape '\\' tidak lengkap di akhir string.", loc)
            nxt = raw[i + 1]
            if nxt not in _ESCAPES:
                raise _error(
                    "INVALID_ESCAPE",
                    "Escape tidak dikenal. Yang didukung: \\\\, \\\", \\n, \\t.",
                    loc,
                    found="\\" + nxt,
                )
            out.append(_ESCAPES[nxt])
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _scan_single(text: str, start: int) -> int | None:
    n = len(text)
    j = start + 1
    while j < n:
        c = text[j]
        if c == "\n":
            return None
        if c == "\\":
            if j + 1 >= n or text[j + 1] == "\n":
                return None
            j += 2
            continue
        if c == '"':
            return j
        j += 1
    return None


def _scan_multi(text: str, start: int) -> int | None:
    n = len(text)
    j = start + 3
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if text.startswith('"""', j):
            return j
        j += 1
    return None


def tokenize(source: str, file: str, limits: Limits | None = None) -> list[Token]:
    limits = limits or Limits()
    text = normalize_newlines(source)
    if text.startswith("\ufeff"):
        text = text[1:]
    n = len(text)
    i = 0
    line = 1
    line_start = 0
    tokens: list[Token] = []

    def too_many() -> FatalDsxError:
        return FatalDsxError(
            Diagnostic(Severity.ERROR, "LIMIT_EXCEEDED", f"Jumlah token melebihi batas {limits.max_tokens}.", Location(file, line, 1))
        )

    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
            line_start = i
            continue
        if ch in " \t":
            i += 1
            continue
        if ch == "#":
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        loc = Location(file, line, i - line_start + 1)
        if ch in _PUNCT:
            tokens.append(Token(_PUNCT[ch], ch, loc))
            i += 1
        elif ch == '"':
            multiline = text.startswith('"""', i)
            end = _scan_multi(text, i) if multiline else _scan_single(text, i)
            if end is None:
                raise _error("UNTERMINATED_STRING", "String tidak ditutup.", loc)
            if multiline:
                raw = text[i + 3 : end]
                if raw.startswith("\n"):
                    raw = raw[1:]
                raw = _TRAILING_INDENT.sub("", raw)
                raw = textwrap.dedent(raw)
                consumed = text[i : end + 3]
            else:
                raw = text[i + 1 : end]
                consumed = text[i : end + 1]
            value = _unescape(raw, loc)
            bad = find_illegal_xml_char(value)
            if bad is not None:
                raise _error(
                    "INVALID_CHARACTER",
                    "String mengandung karakter yang tidak valid untuk dokumen.",
                    loc,
                    found=describe_char(value[bad]),
                )
            tokens.append(Token("STRING", value, loc))
            newlines = consumed.count("\n")
            if newlines:
                line += newlines
                line_start = i + consumed.rfind("\n") + 1
            i += len(consumed)
        elif "0" <= ch <= "9" or (ch == "-" and i + 1 < n and "0" <= text[i + 1] <= "9"):
            match = _NUMBER.match(text, i)
            assert match is not None
            literal = match.group(0)
            end = match.end()
            unit_match = _UNIT.match(text, end)
            if unit_match:
                end = unit_match.end()
            after = text[end : end + 1]
            if after and (after == "." or after == "_" or after.isalnum() and after.isascii()):
                raise _error(
                    "INVALID_NUMBER",
                    "Angka atau satuan tidak valid. Satuan yang didukung: cm, pt, in (tanpa spasi, mis. 1.25cm).",
                    loc,
                    found=text[i : end + 1],
                )
            digits = len(literal.replace("-", "").replace(".", ""))
            if digits > 15:
                raise _error("INVALID_NUMBER", "Angka terlalu besar (maksimum 15 digit).", loc, found=literal)
            value: int | float = float(literal) if "." in literal else int(literal)
            if unit_match:
                tokens.append(Token("QUANTITY", (value, unit_match.group(1)), loc))
            else:
                tokens.append(Token("NUMBER", value, loc))
            i = end
        elif ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ch == "_":
            match = _IDENT.match(text, i)
            assert match is not None
            tokens.append(Token("IDENT", match.group(0), loc))
            i = match.end()
        else:
            raise _error("UNEXPECTED_CHARACTER", "Karakter tidak dikenal.", loc, found=f"{ch!r} ({describe_char(ch)})")
        if len(tokens) > limits.max_tokens:
            raise too_many()
    tokens.append(Token("EOF", None, Location(file, line, i - line_start + 1)))
    return tokens
