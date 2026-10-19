"""Pengikatan dan validasi argumen komponen terhadap skema.

Binder memeriksa nama argumen, tipe, rentang nilai, dan duplikasi. Hasilnya
adalah BoundCall yang sudah bertipe; kesalahan dilaporkan ke DiagnosticBag dan
bind() mengembalikan None.
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from .diagnostics import DiagnosticBag, Location
from .syntax import CallExpr, Expr, StringLit, VarRef
from .schema import ALIASES, VISUAL_KEYS, ParamSpec, Spec
from .mathexpr import MathSyntaxError, ParsedMath, parse_math
from .values import INVALID, CsvRef, ImageRef, Length, TextRef, StyledText, LinkValue, FootnoteValue, type_name

_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_SCALARS = (str, int, float, bool)


class BindContext(Protocol):
    diag: DiagnosticBag
    limits: Any

    def evaluate(self, expr: Expr) -> Any: ...

    def make_ref(self, kind: str, path: str, loc: Location, delimiter: str = ",") -> Any: ...


@dataclass
class BoundCall:
    name: str
    args: dict[str, Any]
    locs: dict[str, Location]
    loc: Location
    spec: Spec | None = field(default=None, repr=False)

    def get(self, key: str, default: Any = None) -> Any:
        return self.args.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.args

    def loc_of(self, key: str) -> Location:
        return self.locs.get(key, self.loc)

    def visual_overrides(self) -> dict[str, Any]:
        return {key: self.args[key] for key in VISUAL_KEYS if key in self.args}


def hint_for(word: str, candidates: Any) -> str | None:
    matches = difflib.get_close_matches(word, list(candidates), n=1, cutoff=0.6)
    return f"Maksud Anda {matches[0]!r}?" if matches else None


class Binder:
    def __init__(self, ctx: BindContext) -> None:
        self.ctx = ctx

    # ------------------------------------------------------------------ bind
    def bind(self, call: CallExpr, spec: Spec) -> BoundCall | None:
        diag = self.ctx.diag
        ok = True
        params = spec.all_params()
        positional = [p for p in spec.params if p.positional]
        provided: dict[str, Any] = {}
        pos_index = 0
        for arg in call.args:
            if arg.name is None:
                if pos_index >= len(positional):
                    hint = None
                    if not positional:
                        hint = "Gunakan format nama=nilai untuk semua argumen."
                    diag.error(
                        "TOO_MANY_ARGUMENTS",
                        f"{call.name}() menerima paling banyak {len(positional)} argumen posisi.",
                        arg.loc,
                        hint=hint,
                    )
                    ok = False
                    continue
                pname = positional[pos_index].name
                pos_index += 1
            else:
                pname = arg.name
                if spec.visual and pname in ALIASES and ALIASES[pname] in params:
                    pname = ALIASES[pname]
                if pname not in params:
                    diag.error(
                        "UNKNOWN_ARGUMENT",
                        f"Argumen {pname!r} tidak dikenal pada {call.name}().",
                        arg.loc,
                        hint=hint_for(pname, params),
                    )
                    ok = False
                    continue
            if pname in provided:
                diag.error("DUPLICATE_ARGUMENT", f"Argumen {pname!r} diberikan lebih dari sekali pada {call.name}().", arg.loc)
                ok = False
                continue
            provided[pname] = arg
        for p in spec.params:
            if p.required and p.name not in provided:
                diag.error("MISSING_ARGUMENT", f"{call.name}() membutuhkan argumen {p.name!r}.", call.loc)
                ok = False
        args: dict[str, Any] = {}
        locs: dict[str, Location] = {}
        for pname, arg in provided.items():
            value = self._convert(params[pname], arg.value, arg.loc, call.name)
            if value is INVALID:
                ok = False
            else:
                args[pname] = value
                locs[pname] = arg.loc
        if not ok:
            return None
        if spec.visual and "hanging_indent" in args:
            if "indent_first" in args:
                diag.error(
                    "INDENT_CONFLICT",
                    "first_line_indent (indent_first) dan hanging_indent tidak boleh diberikan bersamaan; hanging_indent=H sama dengan indent_first=-H.",
                    locs["hanging_indent"],
                )
                return None
            hanging = args.pop("hanging_indent")
            locs["indent_first"] = locs.pop("hanging_indent")
            args["indent_first"] = -hanging if hanging else 0
        return BoundCall(call.name, args, locs, call.loc, spec)

    # --------------------------------------------------------------- convert
    def _convert(self, p: ParamSpec, expr: Expr, loc: Location, comp: str) -> Any:
        if p.type == "name":
            if isinstance(expr, VarRef):
                name = expr.name
            elif isinstance(expr, StringLit):
                name = expr.value
            else:
                self.ctx.diag.error("INVALID_NAME", f"Argumen {p.name!r} pada {comp}() harus berupa nama.", loc)
                return INVALID
            if not _NAME.match(name):
                self.ctx.diag.error(
                    "INVALID_NAME",
                    "Nama harus diawali huruf, hanya berisi huruf, angka, '_' atau '-', maksimum 64 karakter.",
                    loc,
                    found=name,
                )
                return INVALID
            return name
        value = self.ctx.evaluate(expr)
        if value is INVALID:
            return INVALID
        return self._check(p, value, loc, comp)

    def _mismatch(self, p: ParamSpec, comp: str, expected: str, value: object, loc: Location) -> Any:
        self.ctx.diag.error(
            "TYPE_MISMATCH",
            f"Argumen {p.name!r} pada {comp}() harus bertipe {expected}, ditemukan {type_name(value)}.",
            loc,
        )
        return INVALID

    def _invalid(self, p: ParamSpec, comp: str, message: str, value: object, loc: Location, code: str | None = None) -> Any:
        shown = value if not isinstance(value, str) else repr(value)
        self.ctx.diag.error(code or "INVALID_VALUE", f"{message}", loc, found=f"{p.name}={shown}")
        return INVALID

    def _check(self, p: ParamSpec, value: Any, loc: Location, comp: str) -> Any:
        t = p.type
        if t == "enum_ci":
            if not isinstance(value, str):
                return self._mismatch(p, comp, "string", value, loc)
            lowered = value.strip().lower()
            if lowered not in p.choices:
                return self._invalid(p, comp, f"Nilai {p.name!r} tidak valid. Pilihan: {', '.join(p.choices)} (huruf besar/kecil bebas).", value, loc)
            return lowered
        if t == "items":
            return self._check_items(p, value, loc, comp)
        if t == "math":
            if not isinstance(value, str):
                return self._mismatch(p, comp, "string ekspresi matematika", value, loc)
            try:
                return parse_math(value, self.ctx.limits)
            except MathSyntaxError as exc:
                shown = value if len(value) <= 80 else value[:80] + "..."
                self.ctx.diag.error(
                    "MATH_SYNTAX_ERROR",
                    f"Ekspresi matematika tidak valid: {exc.message}",
                    loc,
                    expression=shown,
                    column=exc.position + 1,
                )
                return INVALID
        if t in ("str", "font", "color", "enum"):
            if not isinstance(value, str):
                return self._mismatch(p, comp, "string", value, loc)
            if t == "str":
                if p.max_len is not None and len(value) > p.max_len:
                    return self._invalid(p, comp, f"Argumen {p.name!r} melebihi {p.max_len} karakter.", value[:20] + "...", loc)
                return value
            if t == "enum":
                if value not in p.choices:
                    return self._invalid(
                        p, comp, f"Nilai {p.name!r} tidak valid. Pilihan: {', '.join(p.choices)}.", value, loc
                    )
                return value
            if t == "color":
                if not _COLOR.match(value):
                    return self._invalid(p, comp, "Warna harus berformat #RRGGBB.", value, loc)
                return value.upper()
            # font
            if not value.strip() or len(value) > 100 or any(ord(c) < 32 for c in value):
                return self._invalid(p, comp, "Nama font tidak valid (1-100 karakter tanpa karakter kontrol).", value, loc)
            return value.strip()
        if t == "bool":
            if not isinstance(value, bool):
                return self._mismatch(p, comp, "boolean (true/false)", value, loc)
            return value
        if t == "richtext":
            if isinstance(value, (str, TextRef)):
                return value
            if isinstance(value, list):
                allowed = (str, ParsedMath, StyledText, LinkValue, FootnoteValue)
                for item in value:
                    if not isinstance(item, allowed):
                        return self._mismatch(
                            p,
                            comp,
                            "teks, IMATH(...), BOLD/ITALIC/UNDERLINE(...), LINK(...), atau FOOTNOTE(...) di dalam list",
                            item,
                            loc,
                        )
                if len(value) > self.ctx.limits.max_inline_segments:
                    self.ctx.diag.error("LIMIT_EXCEEDED", f"Segmen teks melebihi batas {self.ctx.limits.max_inline_segments}.", loc)
                    return INVALID
                return list(value)
            return self._mismatch(
                p,
                comp,
                "string, FILE(), atau list segmen (teks/IMATH/BOLD/ITALIC/UNDERLINE/LINK/FOOTNOTE)",
                value,
                loc,
            )
        if t == "num" and isinstance(value, Length):
            if p.unit is None:
                self.ctx.diag.error(
                    "UNIT_NOT_ALLOWED",
                    f"Argumen {p.name!r} pada {comp}() tidak menerima satuan; tulis angka biasa.",
                    loc,
                    found=f"{value.value:g}{value.unit}",
                )
                return INVALID
            value = _convert_length(value, p.unit)
        if t in ("num", "int"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return self._mismatch(p, comp, "bilangan bulat" if t == "int" else "angka", value, loc)
            if t == "int" and not isinstance(value, int):
                return self._mismatch(p, comp, "bilangan bulat", value, loc)
            if isinstance(value, float) and not math.isfinite(value):
                return self._invalid(p, comp, "Angka harus terhingga.", value, loc)
            if p.min is not None and p.max is not None and not (p.min <= value <= p.max):
                return self._invalid(
                    p,
                    comp,
                    (
                        f"Heading level harus berada pada rentang {p.min:g}-{p.max:g}."
                        if p.code == "INVALID_HEADING_LEVEL"
                        else f"Nilai {p.name!r} harus berada pada rentang {p.min:g}-{p.max:g}."
                    ),
                    value,
                    loc,
                    p.code,
                )
            if p.step is not None:
                scaled = value / p.step
                if abs(scaled - round(scaled)) > 1e-9:
                    return self._invalid(p, comp, f"Nilai {p.name!r} harus kelipatan {p.step:g}.", value, loc)
            return value
        if t == "text":
            if isinstance(value, (str, TextRef)):
                return value
            return self._mismatch(p, comp, "string atau referensi file teks (FILE)", value, loc)
        if t == "image":
            if isinstance(value, ImageRef):
                return value
            if isinstance(value, str):
                return self.ctx.make_ref("image", value, loc)
            return self._mismatch(p, comp, "path gambar atau IMAGE()", value, loc)
        if t == "csv":
            if isinstance(value, CsvRef):
                return value
            if isinstance(value, str):
                return self.ctx.make_ref("csv", value, loc)
            return self._mismatch(p, comp, "CSV() atau path CSV", value, loc)
        if t == "strlist":
            if not isinstance(value, list):
                return self._mismatch(p, comp, "list string", value, loc)
            for item in value:
                if not isinstance(item, str):
                    return self._mismatch(p, comp, "list string", item, loc)
            return list(value)
        if t == "rows":
            cell_ok = _SCALARS + (StyledText, LinkValue, FootnoteValue, ParsedMath, list)
            if not isinstance(value, list):
                return self._mismatch(p, comp, "list dari list nilai", value, loc)
            rows: list[list[Any]] = []
            for row in value:
                if not isinstance(row, list):
                    return self._mismatch(p, comp, "list dari list nilai", row, loc)
                cleaned_row: list[Any] = []
                for cell in row:
                    if isinstance(cell, list):
                        for seg in cell:
                            if not isinstance(seg, (str, ParsedMath, StyledText, LinkValue, FootnoteValue)):
                                return self._mismatch(
                                    p, comp, "segmen sel: teks/IMATH/BOLD/LINK/FOOTNOTE", seg, loc
                                )
                        if len(cell) > self.ctx.limits.max_inline_segments:
                            self.ctx.diag.error(
                                "LIMIT_EXCEEDED",
                                f"Segmen sel melebihi batas {self.ctx.limits.max_inline_segments}.",
                                loc,
                            )
                            return INVALID
                        cleaned_row.append(list(cell))
                    elif isinstance(cell, _SCALARS + (StyledText, LinkValue, FootnoteValue, ParsedMath)):
                        cleaned_row.append(cell)
                    else:
                        return self._mismatch(
                            p, comp, "sel: string/angka/boolean atau list segmen kaya", cell, loc
                        )
                rows.append(cleaned_row)
            return rows
        raise AssertionError(f"tipe parameter tidak dikenal: {t}")  # pragma: no cover


    # ------------------------------------------------------------------ items
    def _check_items(self, p: ParamSpec, value: Any, loc: Location, comp: str) -> Any:
        """Daftar item: string, list segmen kaya, atau sub-daftar bersarang."""

        limits = self.ctx.limits
        if not isinstance(value, list):
            return self._mismatch(p, comp, "list item (string/segmen, boleh bersarang)", value, loc)
        count = 0
        segment_types = (str, ParsedMath, StyledText, LinkValue, FootnoteValue)

        def is_rich_segment_list(seq: list) -> bool:
            """List segmen kaya (mengandung IMATH/BOLD/LINK/FOOTNOTE), bukan sub-daftar string."""
            if not seq or any(isinstance(x, list) for x in seq):
                return False
            return any(isinstance(x, (ParsedMath, StyledText, LinkValue, FootnoteValue)) for x in seq)

        def walk(seq: list, depth: int) -> bool:
            nonlocal count
            if depth > limits.max_list_depth:
                self.ctx.diag.error("LIST_TOO_DEEP", f"Daftar bersarang melebihi {limits.max_list_depth} tingkat.", loc)
                return False
            for index, item in enumerate(seq):
                if isinstance(item, list):
                    if is_rich_segment_list(item):
                        for seg in item:
                            if not isinstance(seg, segment_types):
                                self._mismatch(p, comp, "segmen teks/IMATH/BOLD/LINK/FOOTNOTE", seg, loc)
                                return False
                        count += 1
                        if count > limits.max_list_items:
                            self.ctx.diag.error("LIMIT_EXCEEDED", f"Jumlah item daftar melebihi batas {limits.max_list_items}.", loc)
                            return False
                        if len(item) > limits.max_inline_segments:
                            self.ctx.diag.error("LIMIT_EXCEEDED", f"Segmen teks melebihi batas {limits.max_inline_segments}.", loc)
                            return False
                    else:
                        if index == 0:
                            self.ctx.diag.error(
                                "LIST_NESTING_WITHOUT_PARENT",
                                "Sub-daftar harus didahului sebuah item induk pada tingkat yang sama.",
                                loc,
                            )
                            return False
                        if not walk(item, depth + 1):
                            return False
                elif isinstance(item, str):
                    count += 1
                    if count > limits.max_list_items:
                        self.ctx.diag.error("LIMIT_EXCEEDED", f"Jumlah item daftar melebihi batas {limits.max_list_items}.", loc)
                        return False
                else:
                    self._mismatch(p, comp, "string, list segmen, atau sub-daftar", item, loc)
                    return False
            return True

        return value if walk(value, 1) else INVALID


_PT_PER_CM = 72.0 / 2.54


def _convert_length(value: Length, target: str) -> float:
    """Konversi ke satuan dasar parameter (pt atau cm); dibulatkan agar bebas derau float."""
    if value.unit == target:
        result = float(value.value)
    elif value.unit == "in":
        result = value.value * (72.0 if target == "pt" else 2.54)
    elif value.unit == "cm":
        result = value.value * _PT_PER_CM  # target pt
    else:  # pt -> cm
        result = value.value / _PT_PER_CM
    return round(result, 4)
