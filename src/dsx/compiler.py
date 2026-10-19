"""Orkestrasi kompilasi: sumber DSX -> Document IR tervalidasi."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .diagnostics import Diagnostic, DiagnosticBag, DsxSyntaxError, FatalDsxError, Severity
from .ir.builder import IRBuilder
from .ir.nodes import DocumentIR, HeaderFooter, Metadata, PageConfig, PageNumber
from .limits import Deadline, Limits
from .parser import parse
from .resolver import Resolver
from .schema import PAGE_SIZES, SPECS, SUPPORTED_VERSIONS
from .source import ContentStore, Source
from .styles.registry import StyleRegistry
from .templates.registry import TEMPLATES, Template, get_template
from .textutil import collapse_spaces
from .validator import BoundCall, hint_for

_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_FORMAT_TOKEN = re.compile(r"\{[^{}]*\}")
_SINGLE_USE = ("DSX", "DOC", "PAGE", "STYLE", "HEADER", "FOOTER", "PAGENUM")
DEFAULT_MARGIN_CM = 2.54


@dataclass
class CompileResult:
    ir: DocumentIR | None
    diagnostics: DiagnosticBag
    referenced_files: list[str] = field(default_factory=list)


def compile_dsx(
    text: str,
    source: Source,
    *,
    limits: Limits | None = None,
    filename: str = "document.dsx",
    deadline: Deadline | None = None,
) -> CompileResult:
    limits = limits or Limits()
    deadline = deadline or Deadline(limits.max_render_seconds)
    diag = DiagnosticBag(limits.max_diagnostics)
    store = ContentStore(source, limits)
    try:
        ir = _compile(text, store, limits, filename, deadline, diag)
    except DsxSyntaxError as exc:
        diag.add_diagnostic(exc.diagnostic)
        return CompileResult(None, diag, store.referenced())
    except FatalDsxError as exc:
        diag.add_diagnostic(exc.diagnostic)
        return CompileResult(None, diag, store.referenced())
    if diag.has_errors:
        return CompileResult(None, diag, store.referenced())
    return CompileResult(ir, diag, store.referenced())


def _compile(
    text: str,
    store: ContentStore,
    limits: Limits,
    filename: str,
    deadline: Deadline,
    diag: DiagnosticBag,
) -> DocumentIR | None:
    if len(text.encode("utf-8", "replace")) > limits.max_dsx_bytes:
        raise FatalDsxError(
            Diagnostic(Severity.ERROR, "LIMIT_EXCEEDED", f"Ukuran file DSX melebihi batas {limits.max_dsx_bytes} byte.")
        )
    program = parse(text, filename, limits)
    deadline.check()
    if not program.statements:
        diag.warning("EMPTY_DOCUMENT", "File DSX tidak berisi komponen; dokumen kosong akan dibuat.", None)
    resolver = Resolver(program, store, diag, limits)
    resolver.collect()
    binder = resolver.binder

    # --- konfigurasi dan deklarasi -------------------------------------------------
    first_seen: dict[str, Any] = {}
    bound: dict[str, BoundCall] = {}
    styledefs: list[BoundCall] = []
    for call in resolver.config_calls:
        if call.name in _SINGLE_USE:
            if call.name in first_seen:
                diag.error(
                    "DUPLICATE_DECLARATION",
                    f"{call.name}() hanya boleh dideklarasikan satu kali.",
                    call.loc,
                    first_declared=str(first_seen[call.name]),
                )
                continue
            first_seen[call.name] = call.loc
        b = binder.bind(call, SPECS[call.name])
        if b is None:
            continue
        if call.name == "STYLEDEF":
            styledefs.append(b)
        else:
            bound[call.name] = b

    _check_version(bound.get("DSX"), diag)
    metadata, template = _build_metadata(bound.get("DOC"), diag)
    page = _build_page(template, bound.get("PAGE"), diag)
    global_props = bound["STYLE"].visual_overrides() if "STYLE" in bound else {}
    registry = StyleRegistry(template, global_props, diag)
    for b in styledefs:
        registry.define(b)
    registry.finalize()

    builder = IRBuilder(resolver, registry, page, limits, deadline, diag, store)
    header = _build_header_footer(bound.get("HEADER"), builder, diag)
    footer = _build_header_footer(bound.get("FOOTER"), builder, diag)
    page_number = _build_page_number(bound.get("PAGENUM"), builder, diag)

    blocks = builder.build(resolver.content_calls)
    if diag.has_errors:
        return None

    used = set(builder.used_styles) | {"normal"} | set(registry.user_defined_names())
    styles = {}
    for name in sorted(used):
        resolved = registry.get(name)
        if resolved is not None:
            styles[name] = resolved
    if diag.has_errors:
        return None
    return DocumentIR(metadata, page, styles, tuple(blocks), header, footer, page_number, tuple(builder._footnotes), filename)


def _check_version(b: BoundCall | None, diag: DiagnosticBag) -> None:
    if b is None or "version" not in b:
        return
    version = b.args["version"]
    if version not in SUPPORTED_VERSIONS:
        diag.error(
            "UNSUPPORTED_VERSION",
            f"Versi bahasa DSX tidak didukung. Didukung: {', '.join(SUPPORTED_VERSIONS)}.",
            b.loc_of("version"),
            found=f"version={version}",
        )


def _build_metadata(b: BoundCall | None, diag: DiagnosticBag) -> tuple[Metadata, Template]:
    template = TEMPLATES["default"]
    if b is None:
        return Metadata(), template
    name = b.get("template", "default")
    found = get_template(name)
    if found is None:
        diag.error(
            "UNKNOWN_TEMPLATE",
            f"Template {name!r} tidak dikenal. Tersedia: {', '.join(TEMPLATES)}.",
            b.loc_of("template"),
            hint=hint_for(name, TEMPLATES),
        )
        found = template
        name = "default"
    language = b.get("language")
    if language is not None and not _LANG.match(language):
        diag.error("INVALID_VALUE", "Kode bahasa tidak valid (contoh: 'id-ID', 'en-US').", b.loc_of("language"), found=f"language={language!r}")
        language = None
    meta = Metadata(
        title=b.get("title", ""),
        author=b.get("author", ""),
        subject=b.get("subject", ""),
        template=name,
        language=language,
    )
    return meta, found


def _build_page(template: Template, b: BoundCall | None, diag: DiagnosticBag) -> PageConfig:
    args = b.args if b is not None else {}
    size_name = args.get("size", template.page.get("size", "A4"))
    orientation = args.get("orientation", template.page.get("orientation", "portrait"))
    margins = {side: DEFAULT_MARGIN_CM for side in ("top", "bottom", "left", "right")}
    for side in margins:
        key = f"margin_{side}"
        if key in template.page:
            margins[side] = float(template.page[key])
    if "margin" in args:
        for side in margins:
            margins[side] = float(args["margin"])
    for side in margins:
        key = f"margin_{side}"
        if key in args:
            margins[side] = float(args[key])
    width, height = PAGE_SIZES[size_name]
    if orientation == "landscape":
        width, height = height, width
    page = PageConfig(
        size_name, orientation, width, height, margins["top"], margins["bottom"], margins["left"], margins["right"]
    )
    loc = b.loc if b is not None else None
    if page.content_width < 2.0 or page.content_height < 2.0:
        diag.error(
            "PAGE_MARGIN_TOO_LARGE",
            "Margin terlalu besar: area isi halaman kurang dari 2 cm.",
            loc,
            found=f"area isi {page.content_width:.2f} x {page.content_height:.2f} cm",
        )
    return page


def _header_base(align: str) -> dict[str, Any]:
    return {
        "align": align,
        "indent_first": 0,
        "indent_left": 0,
        "indent_right": 0,
        "space_before": 0,
        "space_after": 0,
        "page_break_before": False,
    }


def _build_header_footer(b: BoundCall | None, builder: IRBuilder, diag: DiagnosticBag) -> HeaderFooter | None:
    if b is None:
        return None
    selected = builder._select_style(b)
    if selected is None:
        return None
    st, _role, _level = selected
    text = collapse_spaces(" ".join(collapse_spaces(line) for line in b.args["text"].split("\n")))
    if not text:
        diag.warning("EMPTY_TEXT", f"Teks {b.name}() kosong dan diabaikan.", b.loc)
        return None
    builder.used_styles.add(st.name)
    overrides = {**_header_base("center"), **b.visual_overrides()}
    return HeaderFooter(text, st.name, overrides)


def _build_page_number(b: BoundCall | None, builder: IRBuilder, diag: DiagnosticBag) -> PageNumber | None:
    if b is None:
        return None
    selected = builder._select_style(b)
    if selected is None:
        return None
    st, _role, _level = selected
    fmt = b.get("format", "{page}")
    stripped = _FORMAT_TOKEN.sub("", fmt)
    tokens = _FORMAT_TOKEN.findall(fmt)
    if any(t not in ("{page}", "{pages}") for t in tokens) or "{" in stripped or "}" in stripped:
        diag.error(
            "INVALID_VALUE",
            "Format nomor halaman hanya boleh memakai {page} dan {pages}.",
            b.loc_of("format"),
            found=f"format={fmt!r}",
        )
        return None
    if "\n" in fmt:
        diag.error("INVALID_VALUE", "Format nomor halaman tidak boleh multiline.", b.loc_of("format"))
        return None
    builder.used_styles.add(st.name)
    overrides = {**_header_base("center"), **b.visual_overrides()}
    return PageNumber(b.get("position", "footer"), fmt, st.name, overrides)
