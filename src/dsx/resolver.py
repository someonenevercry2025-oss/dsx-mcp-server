"""Resolusi deklarasi, variabel, dan referensi file.

Deklarasi LET dan komponen konfigurasi dikumpulkan lebih dulu (hoisting), jadi
variabel boleh dipakai sebelum dideklarasikan. Komponen isi tetap dirender
sesuai urutan kemunculannya.
"""

from __future__ import annotations

import posixpath
import re
from typing import Any

from .diagnostics import DiagnosticBag, Location
from .limits import Limits
from .schema import RESERVED_NAMES, SPECS, VALUE_FUNCTIONS
from .source import ContentStore, SourceError, normalize_relpath
from .syntax import (
    BoolLit,
    CallExpr,
    CallStmt,
    Expr,
    LetStmt,
    ListLit,
    NumberLit,
    Program,
    QuantityLit,
    StringLit,
    VarRef,
)
from .diagnostics import Diagnostic, FatalDsxError, Severity
from .validator import Binder, hint_for
from .values import INVALID, CsvRef, ImageRef, Length, TextRef

_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_EXT = {
    "text": {".txt"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".bmp"},
    "csv": {".csv"},
}
_KIND_LABEL = {"text": "FILE", "image": "IMAGE", "csv": "CSV"}
_DELIMITERS = (",", ";", "\t", "|")


class Resolver:
    def __init__(self, program: Program, store: ContentStore, diag: DiagnosticBag, limits: Limits) -> None:
        self.program = program
        self.store = store
        self.diag = diag
        self.limits = limits
        self.binder = Binder(self)
        self.config_calls: list[CallExpr] = []
        self.content_calls: list[CallExpr] = []
        self._lets: dict[str, LetStmt] = {}
        self._values: dict[str, Any] = {}
        self._stack: list[str] = []

    # --------------------------------------------------------------- collect
    def collect(self) -> None:
        for stmt in self.program.statements:
            if isinstance(stmt, LetStmt):
                self._collect_let(stmt)
            elif isinstance(stmt, CallStmt):
                self._collect_call(stmt.call)
        if len(self.content_calls) + len(self.config_calls) > self.limits.max_components:
            raise FatalDsxError(
                Diagnostic(Severity.ERROR, "LIMIT_EXCEEDED", f"Jumlah komponen melebihi batas {self.limits.max_components}.")
            )
        for name in list(self._lets):
            self._variable(name, self._lets[name].loc, report_undefined=False)

    def _collect_let(self, stmt: LetStmt) -> None:
        name = stmt.name
        if not _VAR_NAME.match(name):
            self.diag.error(
                "INVALID_NAME",
                "Nama variabel hanya boleh berisi huruf, angka, dan '_' (tanpa '-') dan tidak diawali angka.",
                stmt.loc,
                found=name,
            )
            return
        if name in RESERVED_NAMES:
            self.diag.error("RESERVED_NAME", f"{name!r} adalah kata cadangan dan tidak dapat dipakai sebagai nama variabel.", stmt.loc)
            return
        if name in self._lets:
            self.diag.error(
                "DUPLICATE_VARIABLE",
                f"Variabel {name!r} sudah dideklarasikan.",
                stmt.loc,
                first_declared=str(self._lets[name].loc),
            )
            return
        self._lets[name] = stmt

    def _collect_call(self, call: CallExpr) -> None:
        spec = SPECS.get(call.name)
        if spec is None:
            self.diag.error(
                "UNKNOWN_COMPONENT",
                f"Komponen {call.name!r} tidak dikenal.",
                call.loc,
                hint=hint_for(call.name, SPECS),
            )
            return
        if spec.category == "value":
            self.diag.error(
                "NOT_A_COMPONENT",
                f"{call.name}() adalah fungsi nilai dan hanya dapat dipakai sebagai argumen atau pada LET.",
                call.loc,
            )
            return
        if spec.category in ("meta", "styledef"):
            self.config_calls.append(call)
        else:
            self.content_calls.append(call)

    # -------------------------------------------------------------- evaluate
    def evaluate(self, expr: Expr) -> Any:
        if isinstance(expr, (StringLit, NumberLit, BoolLit)):
            return expr.value
        if isinstance(expr, QuantityLit):
            return Length(expr.value, expr.unit)
        if isinstance(expr, ListLit):
            items = [self.evaluate(item) for item in expr.items]
            if any(item is INVALID for item in items):
                return INVALID
            return items
        if isinstance(expr, VarRef):
            return self._variable(expr.name, expr.loc)
        if isinstance(expr, CallExpr):
            return self._call(expr)
        raise AssertionError(f"ekspresi tidak dikenal: {expr!r}")  # pragma: no cover

    def _variable(self, name: str, loc: Location, report_undefined: bool = True) -> Any:
        if name in self._values:
            return self._values[name]
        stmt = self._lets.get(name)
        if stmt is None:
            if report_undefined:
                self.diag.error(
                    "UNDEFINED_VARIABLE",
                    f"Variabel {name!r} tidak ditemukan.",
                    loc,
                    hint=hint_for(name, self._lets),
                )
            return INVALID
        if name in self._stack:
            chain = self._stack[self._stack.index(name) :] + [name]
            self.diag.error(
                "VARIABLE_CYCLE",
                "Definisi variabel saling merujuk (siklus).",
                self._lets[name].loc,
                chain=" -> ".join(chain),
            )
            return INVALID
        if len(self._stack) >= self.limits.max_variable_depth:
            self.diag.error(
                "LIMIT_EXCEEDED",
                f"Rantai referensi variabel melebihi kedalaman {self.limits.max_variable_depth}.",
                stmt.loc,
            )
            self._values[name] = INVALID
            return INVALID
        self._stack.append(name)
        try:
            value = self.evaluate(stmt.value)
        finally:
            self._stack.pop()
        self._values[name] = value
        return value

    def _call(self, call: CallExpr) -> Any:
        if call.name in VALUE_FUNCTIONS:
            bound = self.binder.bind(call, SPECS[call.name])
            if bound is None:
                return INVALID
            if call.name == "IMATH":
                return bound.args["expr"]  # ParsedMath tervalidasi (matematika sebaris)
            if call.name == "BOLD":
                from .values import StyledText
                return StyledText(str(bound.args["text"]), bold=True)
            if call.name == "ITALIC":
                from .values import StyledText
                return StyledText(str(bound.args["text"]), italic=True)
            if call.name == "UNDERLINE":
                from .values import StyledText
                return StyledText(str(bound.args["text"]), underline=True)
            if call.name == "LINK":
                from .values import LinkValue
                url = str(bound.args["url"]).strip()
                if not url or not (url.startswith("http://") or url.startswith("https://") or url.startswith("mailto:")):
                    self.diag.error(
                        "INVALID_URL",
                        "URL hyperlink harus dimulai dengan http://, https://, atau mailto:.",
                        bound.loc_of("url"),
                        found=url[:80],
                    )
                    return INVALID
                return LinkValue(str(bound.args["text"]), url)
            if call.name == "FOOTNOTE":
                from .values import FootnoteValue
                note = str(bound.args["text"]).strip()
                if not note:
                    self.diag.error("EMPTY_FOOTNOTE", "FOOTNOTE() membutuhkan teks yang tidak kosong.", bound.loc_of("text"))
                    return INVALID
                return FootnoteValue(note)
            kind = {"FILE": "text", "IMAGE": "image", "CSV": "csv"}[call.name]
            return self.make_ref(kind, bound.args["path"], bound.loc_of("path"), bound.get("delimiter", ","))
        if call.name in SPECS:
            self.diag.error(
                "NOT_A_VALUE_FUNCTION",
                f"{call.name}() adalah komponen dokumen, bukan fungsi nilai; hanya FILE(), IMAGE(), CSV(), IMATH(), BOLD(), ITALIC(), UNDERLINE(), LINK(), dan FOOTNOTE() yang dapat dipakai sebagai nilai.",
                call.loc,
            )
        else:
            self.diag.error("UNKNOWN_FUNCTION", f"Fungsi {call.name!r} tidak dikenal.", call.loc, hint=hint_for(call.name, VALUE_FUNCTIONS))
        return INVALID

    # ------------------------------------------------------------ references
    def make_ref(self, kind: str, path: str, loc: Location, delimiter: str = ",") -> Any:
        label = _KIND_LABEL[kind]
        try:
            rel = normalize_relpath(path)
        except SourceError as exc:
            self.diag.error(exc.code, exc.message, loc, reference=path)
            return INVALID
        if kind == "csv" and delimiter not in _DELIMITERS:
            self.diag.error(
                "INVALID_VALUE",
                "Delimiter CSV harus salah satu dari ',' ';' tab atau '|'.",
                loc,
                found=repr(delimiter),
            )
            return INVALID
        ext = posixpath.splitext(rel)[1].lower()
        if ext not in _ALLOWED_EXT[kind]:
            self.diag.error(
                "UNSUPPORTED_FILE_TYPE",
                f"{label}() hanya mendukung ekstensi: {', '.join(sorted(_ALLOWED_EXT[kind]))}.",
                loc,
                reference=rel,
            )
            return INVALID
        try:
            if kind == "text":
                self.store.text(rel)
                return TextRef(rel)
            if kind == "image":
                self.store.image(rel)
                return ImageRef(rel)
            self.store.csv_rows(rel, delimiter)
            return CsvRef(rel, delimiter)
        except SourceError as exc:
            self.diag.error(exc.code, exc.message, loc, reference=rel)
            return INVALID
