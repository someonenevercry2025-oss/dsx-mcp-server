"""IR builder: mengubah komponen isi yang sudah terikat menjadi blok Document IR."""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from ..diagnostics import DiagnosticBag, Location
from ..limits import Deadline, Limits
from ..resolver import Resolver
from ..schema import SPECS
from ..source import ContentStore
from ..styles.registry import ResolvedStyle, StyleRegistry
from ..syntax import CallExpr
from ..textutil import collapse_spaces
from ..validator import BoundCall, hint_for
from ..values import CsvRef, TextRef, StyledText, LinkValue, FootnoteValue
from ..styles.defaults import CALLOUT_THEMES
from ..mathexpr import ParsedMath
from .nodes import Block, Callout, Figure, ImageAsset, ListBlock, ListItem, MathBlock, MathSeg, PageConfig, Paragraph, Table, TableCell, TextBlock, TextSeg, LinkSeg, FootnoteSeg, TocBlock, FootnoteDef

_HEADING_SHORTCUT = re.compile(r"^H([1-9])$")


def split_paragraphs(text: str, preserve_breaks: bool) -> list[str]:
    """Aturan TEXTBLOCK (Blueprint V.3): baris kosong memisahkan paragraf,
    baris berurutan digabung menjadi satu paragraf."""
    groups: list[list[str]] = []
    current: list[str] = []
    for line in text.split("\n"):
        if line.strip() == "":
            if current:
                groups.append(current)
                current = []
        else:
            current.append(line)
    if current:
        groups.append(current)
    result: list[str] = []
    for lines in groups:
        if preserve_breaks:
            result.append("\n".join(line.rstrip() for line in lines))
        else:
            result.append(collapse_spaces(" ".join(collapse_spaces(line) for line in lines)))
    return result



def raw_to_segments(raw_items: list, footnote_sink: list, footnote_seq: list) -> tuple[list, str]:
    """Ubah list nilai (str/StyledText/Link/Footnote/ParsedMath) menjadi Segment + plain text.

    footnote_seq is a single-element list holding the current counter (mutable).
    """
    segments: list = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            text = re.sub(r"[ \t\f\v\n]+", " ", "".join(buffer))
            buffer.clear()
            if text:
                segments.append(TextSeg(text))

    for item in raw_items:
        if isinstance(item, ParsedMath):
            flush()
            segments.append(MathSeg(item.source, item.tree))
        elif isinstance(item, StyledText):
            flush()
            t = re.sub(r"[ \t\f\v\n]+", " ", item.text)
            if t:
                segments.append(TextSeg(t, bold=item.bold, italic=item.italic, underline=item.underline))
        elif isinstance(item, LinkValue):
            flush()
            t = re.sub(r"[ \t\f\v\n]+", " ", item.text)
            if t:
                segments.append(LinkSeg(t, item.url, bold=item.bold, italic=item.italic, underline=item.underline))
        elif isinstance(item, FootnoteValue):
            flush()
            footnote_seq[0] += 1
            fid = footnote_seq[0]
            footnote_sink.append(FootnoteDef(fid, item.text))
            segments.append(FootnoteSeg(fid, item.text))
        else:
            buffer.append(str(item))
    flush()
    plain_parts = []
    for s in segments:
        if isinstance(s, TextSeg):
            plain_parts.append(s.text)
        elif isinstance(s, LinkSeg):
            plain_parts.append(s.text)
        elif isinstance(s, FootnoteSeg):
            plain_parts.append(f"[{s.note_id}]")
    plain = "".join(plain_parts)
    needs = any(
        isinstance(s, (MathSeg, LinkSeg, FootnoteSeg))
        or (isinstance(s, TextSeg) and (s.bold or s.italic or s.underline))
        for s in segments
    )
    return (segments if needs else []), plain


class IRBuilder:
    def __init__(
        self,
        resolver: Resolver,
        registry: StyleRegistry,
        page: PageConfig,
        limits: Limits,
        deadline: Deadline,
        diag: DiagnosticBag,
        store: ContentStore,
    ) -> None:
        self.resolver = resolver
        self.registry = registry
        self.page = page
        self.limits = limits
        self.deadline = deadline
        self.diag = diag
        self.store = store
        self.used_styles: set[str] = set()
        self._paragraph_count = 0
        self._footnotes: list[FootnoteDef] = []
        self._footnote_seq = 0

    # ------------------------------------------------------------ public API
    def build(self, calls: list[CallExpr]) -> list[Block]:
        blocks: list[Block] = []
        pending_break: Location | None = None
        for call in calls:
            self.deadline.check()
            bound = self.resolver.binder.bind(call, SPECS[call.name])
            if bound is None:
                continue
            if call.name == "PAGEBREAK":
                if pending_break is not None:
                    self.diag.warning("DUPLICATE_PAGEBREAK", "PAGEBREAK berurutan digabung menjadi satu.", call.loc)
                else:
                    pending_break = call.loc
                continue
            new_blocks = self._build_call(bound)
            for block in new_blocks:
                if pending_break is not None:
                    block = self._with_break(block)
                    pending_break = None
                blocks.append(block)
        if pending_break is not None:
            self.diag.warning("TRAILING_PAGEBREAK", "PAGEBREAK tanpa konten sesudahnya diabaikan.", pending_break)
        return blocks

    def _build_call(self, b: BoundCall) -> list[Block]:
        name = b.name
        if name in ("TEXT", "P") or _HEADING_SHORTCUT.match(name):
            para = self._text_component(b)
            return [para] if para is not None else []
        if name == "TEXTBLOCK":
            block = self._textblock(b)
            return [block] if block is not None else []
        if name == "FIGURE":
            fig = self._figure(b)
            return [fig] if fig is not None else []
        if name == "TABLE":
            table = self._table(b)
            return [table] if table is not None else []
        if name in ("LIST", "BULLET"):
            lst = self._list(b)
            return [lst] if lst is not None else []
        if name == "CALLOUT":
            callout = self._callout(b)
            return [callout] if callout is not None else []
        if name == "MATH":
            return [self._math(b)]
        if name == "TOC":
            return [self._toc(b)]
        raise AssertionError(f"komponen isi tidak dikenal: {name}")  # pragma: no cover

    # ------------------------------------------------------------ page break
    def _with_break(self, block: Block) -> Block:
        if isinstance(block, Paragraph):
            return self._paragraph_with_break(block)
        if isinstance(block, TextBlock):
            first = self._paragraph_with_break(block.paragraphs[0])
            return dataclasses.replace(block, paragraphs=(first,) + block.paragraphs[1:])
        return dataclasses.replace(block, page_break_before=True)

    @staticmethod
    def _paragraph_with_break(p: Paragraph) -> Paragraph:
        return dataclasses.replace(
            p,
            overrides={**p.overrides, "page_break_before": True},
            effective={**p.effective, "page_break_before": True},
        )

    # ----------------------------------------------------------------- style
    def _select_style(
        self,
        b: BoundCall,
        style_key: str = "style",
        role: str | None = None,
        level: int | None = None,
    ) -> tuple[ResolvedStyle, str, int | None] | None:
        style_name = b.get(style_key)
        if style_name is not None:
            loc = b.loc_of(style_key)
            if not self.registry.exists(style_name):
                self.diag.error(
                    "STYLE_NOT_FOUND",
                    f"Style {style_name!r} tidak ditemukan.",
                    loc,
                    hint=hint_for(style_name, self.registry.names()),
                )
                return None
            st = self.registry.get(style_name)
            if st is None:
                return None  # kesalahan style sudah dilaporkan
            if role is not None and st.role not in (None, "body") and role != st.role:
                self.diag.error(
                    "ROLE_STYLE_CONFLICT",
                    f"Role {role!r} bertentangan dengan role style {style_name!r} ({st.role!r}).",
                    loc,
                )
                return None
            eff_role = role if role is not None else (st.role or "body")
        else:
            eff_role = role if role is not None else "body"
            st = None
        eff_level: int | None = None
        if eff_role == "heading":
            if level is not None:
                eff_level = level
                if st is not None and st.role == "heading" and st.level is not None and st.level != level:
                    self.diag.error(
                        "ROLE_STYLE_CONFLICT",
                        f"Level {level} bertentangan dengan level style {st.name!r} ({st.level}).",
                        b.loc_of("level") if "level" in b else b.loc,
                    )
                    return None
            elif st is not None and st.role == "heading":
                eff_level = st.level
            if eff_level is None:
                self.diag.error(
                    "MISSING_HEADING_LEVEL",
                    "Role 'heading' membutuhkan level 1-9 (melalui argumen level atau style).",
                    b.loc,
                )
                return None
            if st is None:
                st = self.registry.heading_style(eff_level)
        else:
            if level is not None:
                self.diag.error("LEVEL_WITHOUT_HEADING", "Argumen level hanya berlaku untuk role 'heading'.", b.loc_of("level") if "level" in b else b.loc)
                return None
            if st is None:
                st = self.registry.style_for_role(eff_role)
        if st is None:
            return None
        return st, eff_role, eff_level

    def _make_paragraph(
        self,
        text: str,
        st: ResolvedStyle,
        role: str,
        level: int | None,
        overrides: dict[str, Any],
        loc: Location,
        segments: tuple = (),
    ) -> Paragraph:
        self._paragraph_count += 1
        if self._paragraph_count > self.limits.max_paragraphs:
            from ..diagnostics import Diagnostic, FatalDsxError, Severity

            raise FatalDsxError(
                Diagnostic(Severity.ERROR, "LIMIT_EXCEEDED", f"Jumlah paragraf melebihi batas {self.limits.max_paragraphs}.", loc)
            )
        self.used_styles.add(st.name)
        effective = {**st.props, **overrides}
        if ("indent_left" in overrides or "indent_first" in overrides) and effective["indent_left"] + effective["indent_first"] < -1e-6:
            self.diag.warning(
                "INDENT_OUTSIDE_MARGIN",
                "Baris pertama paragraf berada di luar margin kiri (indent_left + indent_first < 0). "
                "Untuk hanging indent, kombinasikan hanging_indent dengan left_indent yang sama besar.",
                loc,
            )
        return Paragraph(
            text=text,
            role=role,
            level=level,
            style=st.name,
            overrides=dict(overrides),
            effective=effective,
            source=loc,
            segments=segments,
        )

    # ------------------------------------------------------------------ text
    def _text_value(self, value: Any) -> str:
        if isinstance(value, TextRef):
            return self.store.text(value.path)
        return value

    def _role_level_args(self, b: BoundCall) -> tuple[str | None, int | None]:
        m = _HEADING_SHORTCUT.match(b.name)
        if m:
            return "heading", int(m.group(1))
        return b.get("role"), b.get("level")

    def _text_component(self, b: BoundCall) -> Paragraph | None:
        role, level = self._role_level_args(b)
        selected = self._select_style(b, role=role, level=level)
        if selected is None:
            return None
        st, eff_role, eff_level = selected
        raw = b.args["text"]
        if isinstance(raw, list):
            return self._segmented_paragraph(b, raw, st, eff_role, eff_level)
        parts = split_paragraphs(self._text_value(raw), preserve_breaks=eff_role == "code")
        if not parts:
            self.diag.warning("EMPTY_TEXT", f"{b.name}() menerima teks kosong; paragraf kosong dibuat.", b.loc_of("text"))
            text = ""
        else:
            if len(parts) > 1:
                self.diag.warning(
                    "TEXT_MULTIPLE_PARAGRAPHS",
                    f"Teks pada {b.name}() berisi beberapa paragraf dan digabung menjadi satu; gunakan TEXTBLOCK() untuk memisahkannya.",
                    b.loc_of("text"),
                )
            text = ("\n\n" if eff_role == "code" else " ").join(parts)
        return self._make_paragraph(text, st, eff_role, eff_level, b.visual_overrides(), b.loc)

    def _segmented_paragraph(self, b: BoundCall, raw: list, st: ResolvedStyle, role: str, level: int | None) -> Paragraph | None:
        """Paragraf dari list segmen: teks, IMATH, BOLD/ITALIC/UNDERLINE, LINK, FOOTNOTE."""
        if role == "code":
            self.diag.error(
                "INLINE_MATH_NOT_ALLOWED",
                "Segmen list tidak dapat dipakai pada role 'code'; teks kode harus berupa string biasa.",
                b.loc_of("text"),
            )
            return None
        segments: list = []
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                text = re.sub(r"[ \t\f\v\n]+", " ", "".join(buffer))
                buffer.clear()
                if text:
                    segments.append(TextSeg(text))

        for item in raw:
            if isinstance(item, ParsedMath):
                flush()
                segments.append(MathSeg(item.source, item.tree))
            elif isinstance(item, StyledText):
                flush()
                t = re.sub(r"[ \t\f\v\n]+", " ", item.text)
                if t:
                    segments.append(TextSeg(t, bold=item.bold, italic=item.italic, underline=item.underline))
            elif isinstance(item, LinkValue):
                flush()
                t = re.sub(r"[ \t\f\v\n]+", " ", item.text)
                if t:
                    segments.append(
                        LinkSeg(t, item.url, bold=item.bold, italic=item.italic, underline=item.underline)
                    )
            elif isinstance(item, FootnoteValue):
                flush()
                self._footnote_seq += 1
                fid = self._footnote_seq
                self._footnotes.append(FootnoteDef(fid, item.text))
                segments.append(FootnoteSeg(fid, item.text))
            else:
                buffer.append(str(item))
        flush()
        # trim outer plain TextSeg only
        if segments and isinstance(segments[0], TextSeg) and not (segments[0].bold or segments[0].italic or segments[0].underline):
            segments[0] = TextSeg(segments[0].text.lstrip(" "), segments[0].bold, segments[0].italic, segments[0].underline)
        if segments and isinstance(segments[-1], TextSeg) and not (segments[-1].bold or segments[-1].italic or segments[-1].underline):
            segments[-1] = TextSeg(segments[-1].text.rstrip(" "), segments[-1].bold, segments[-1].italic, segments[-1].underline)
        segments = [s for s in segments if not (isinstance(s, TextSeg) and s.text == "")]
        needs_segments = any(
            isinstance(s, (MathSeg, LinkSeg, FootnoteSeg))
            or (isinstance(s, TextSeg) and (s.bold or s.italic or s.underline))
            for s in segments
        )
        plain = "".join(
            s.text if isinstance(s, (TextSeg, LinkSeg)) else ""
            for s in segments
        )
        if not segments:
            self.diag.warning("EMPTY_TEXT", f"{b.name}() menerima teks kosong; paragraf kosong dibuat.", b.loc_of("text"))
        return self._make_paragraph(
            plain, st, role, level, b.visual_overrides(), b.loc, tuple(segments) if needs_segments else ()
        )

    def _toc(self, b: BoundCall) -> TocBlock:
        title = str(b.get("title", "Daftar Isi"))
        depth = int(b.get("depth", 3))
        return TocBlock(title, depth, False, b.loc)

    def _textblock(self, b: BoundCall) -> TextBlock | None:
        role, level = self._role_level_args(b)
        selected = self._select_style(b, role=role, level=level)
        if selected is None:
            return None
        st, eff_role, eff_level = selected
        if eff_role == "heading":
            self.diag.error(
                "HEADING_IN_TEXTBLOCK",
                "TEXTBLOCK() tidak dapat berperan sebagai heading; gunakan TEXT() atau H1()-H9().",
                b.loc,
            )
            return None
        parts = split_paragraphs(self._text_value(b.args["text"]), preserve_breaks=eff_role == "code")
        if not parts:
            self.diag.warning("EMPTY_CONTENT", "Konten TEXTBLOCK() kosong; tidak ada paragraf yang dibuat.", b.loc_of("text"))
            return None
        overrides = b.visual_overrides()
        paragraphs = tuple(self._make_paragraph(t, st, eff_role, eff_level, overrides, b.loc) for t in parts)
        return TextBlock(paragraphs, b.loc)

    # ---------------------------------------------------------------- figure
    def _caption(self, b: BoundCall, text: str, overrides: dict[str, Any] | None = None) -> Paragraph | None:
        selected = self._select_style(b, style_key="caption_style", role="caption")
        if selected is None:
            return None
        st, eff_role, eff_level = selected
        cleaned = collapse_spaces(" ".join(collapse_spaces(l) for l in text.split("\n")))
        return self._make_paragraph(cleaned, st, "caption", None, overrides or {}, b.loc_of("caption"))

    def _figure(self, b: BoundCall) -> Figure | None:
        ref = b.args["src"]
        info = self.store.image(ref.path)
        data = self.store.bytes_of(ref.path)
        native_w = info.px_width / info.dpi_x * 2.54
        native_h = info.px_height / info.dpi_y * 2.54
        width = b.get("width")
        height = b.get("height")
        if width is not None and height is not None:
            w, h = float(width), float(height)
        elif width is not None:
            w = float(width)
            h = w * native_h / native_w
        elif height is not None:
            h = float(height)
            w = h * native_w / native_h
        else:
            w, h = native_w, native_h
        max_w = self.page.content_width
        max_h = self.page.content_height
        factor = min(1.0, max_w / w, max_h / h)
        if factor < 1.0:
            self.diag.warning(
                "FIGURE_RESIZED",
                f"Gambar {ref.path!r} diperkecil agar muat pada area halaman ({max_w:.2f} x {max_h:.2f} cm).",
                b.loc,
            )
            w *= factor
            h *= factor
        w = max(w, 0.01)
        h = max(h, 0.01)
        caption = None
        if "caption" in b:
            caption = self._caption(b, b.args["caption"])
            if caption is None:
                return None
        asset = ImageAsset(ref.path, data, info.content_type)
        return Figure(asset, round(w, 4), round(h, 4), b.get("align", "center"), b.get("alt", ""), caption, False, b.loc)

    # ----------------------------------------------------------------- table
    def _to_cell(self, value: Any) -> TableCell:
        """Nilai sel → TableCell (dukung list segmen kaya)."""
        if isinstance(value, list):
            footnote_seq = [self._footnote_seq]
            segs, plain = raw_to_segments(value, self._footnotes, footnote_seq)
            self._footnote_seq = footnote_seq[0]
            return TableCell(plain, tuple(segs))
        if isinstance(value, (StyledText, LinkValue, FootnoteValue, ParsedMath)):
            footnote_seq = [self._footnote_seq]
            segs, plain = raw_to_segments([value], self._footnotes, footnote_seq)
            self._footnote_seq = footnote_seq[0]
            return TableCell(plain, tuple(segs))
        if isinstance(value, bool):
            t = "true" if value else "false"
        elif isinstance(value, float):
            t = format(value, ".15g")
        else:
            t = str(value)
        return TableCell(t, ())

    def _table(self, b: BoundCall) -> Table | None:
        has_data = "data" in b
        has_inline = "rows" in b or "headers" in b
        if has_data and has_inline:
            self.diag.error("TABLE_CONFLICT", "TABLE() tidak boleh memakai data sekaligus headers/rows.", b.loc)
            return None
        if not has_data and not has_inline:
            self.diag.error("MISSING_ARGUMENT", "TABLE() membutuhkan headers/rows atau data=CSV(...).", b.loc)
            return None
        header: list[str] | None
        body: list[list[str]]
        if has_data:
            ref: CsvRef = b.args["data"]
            rows = self.store.csv_rows(ref.path, ref.delimiter)
            if not rows:
                self.diag.error("EMPTY_TABLE", "CSV tidak berisi baris data.", b.loc_of("data"), reference=ref.path)
                return None
            if b.get("header", True):
                header = list(rows[0])
                body = [list(r) for r in rows[1:]]
            else:
                header = None
                body = [list(r) for r in rows]
        else:
            if "header" in b:
                self.diag.error("ARGUMENT_NOT_APPLICABLE", "Argumen 'header' hanya berlaku bersama data=CSV(...).", b.loc_of("header"))
                return None
            header = list(b.args["headers"]) if "headers" in b else None
            body = [[self._to_cell(c) for c in row] for row in b.get("rows", [])]
        columns = len(header) if header is not None else (len(body[0]) if body else 0)
        if columns == 0:
            self.diag.error("EMPTY_TABLE", "Tabel tidak memiliki kolom.", b.loc)
            return None
        ok = True
        for number, row in enumerate(body, start=1):
            if len(row) != columns:
                self.diag.error(
                    "TABLE_ROW_WIDTH_MISMATCH",
                    f"Baris data ke-{number} memiliki {len(row)} kolom, diharapkan {columns}.",
                    b.loc_of("rows") if "rows" in b else b.loc,
                )
                ok = False
        if not ok:
            return None
        total_rows = len(body) + (1 if header is not None else 0)
        if columns > self.limits.max_table_columns or total_rows > self.limits.max_table_rows + 1 or total_rows * columns > self.limits.max_table_cells:
            self.diag.error(
                "LIMIT_EXCEEDED",
                f"Ukuran tabel melebihi batas ({self.limits.max_table_columns} kolom, {self.limits.max_table_rows} baris, {self.limits.max_table_cells} sel).",
                b.loc,
            )
            return None
        caption = None
        if "caption" in b:
            caption = self._caption(b, b.args["caption"])
            if caption is None:
                return None
        def as_cells(row):
            out = []
            for c in row:
                if isinstance(c, TableCell):
                    out.append(c)
                else:
                    out.append(self._to_cell(c))
            return tuple(out)

        header_cells = as_cells(header) if header is not None else None
        body_cells = tuple(as_cells(r) for r in body)
        # length limit on plain text
        for cell in (list(header_cells) if header_cells else []) + [c for row in body_cells for c in row]:
            if len(cell.text) > self.limits.max_cell_chars:
                self.diag.error("LIMIT_EXCEEDED", f"Sel tabel melebihi {self.limits.max_cell_chars} karakter.", b.loc)
                return None
        return Table(
            header_cells,
            body_cells,
            b.get("align", "center"),
            caption,
            False,
            b.loc,
        )

    # ------------------------------------------------------------------ list
    def _list(self, b: BoundCall) -> ListBlock | None:
        selected = self._select_style(b, role=None) if "style" in b else None
        if "style" in b and selected is None:
            return None
        st = selected[0] if selected else self.registry.get("list-item")
        if st is None:
            return None
        items: list[ListItem] = []
        footnote_seq = [self._footnote_seq]

        def is_segment_list(entry: list) -> bool:
            """True hanya bila list memuat segmen kaya (bukan sub-daftar string murni)."""
            if not entry or any(isinstance(x, list) for x in entry):
                return False
            return any(isinstance(x, (ParsedMath, StyledText, LinkValue, FootnoteValue)) for x in entry)

        def walk(seq: list, level: int) -> None:
            for entry in seq:
                if isinstance(entry, list) and not is_segment_list(entry):
                    walk(entry, level + 1)
                    continue
                if isinstance(entry, list):
                    # rich segment item
                    segs, plain = raw_to_segments(entry, self._footnotes, footnote_seq)
                    if not plain and not segs:
                        self.diag.warning("EMPTY_LIST_ITEM", "Item daftar kosong dilewati.", b.loc_of("items"))
                        continue
                    items.append(ListItem(plain, level, (), tuple(segs)))
                    continue
                # plain string item
                parts = split_paragraphs(str(entry), preserve_breaks=False)
                if not parts:
                    self.diag.warning("EMPTY_LIST_ITEM", "Item daftar kosong dilewati.", b.loc_of("items"))
                    continue
                items.append(ListItem(parts[0], level, tuple(parts[1:]), ()))

        walk(b.args["items"], 0)
        self._footnote_seq = footnote_seq[0]
        if not items:
            self.diag.warning("EMPTY_LIST", f"{b.name}() tidak memiliki item; tidak ada daftar yang dibuat.", b.loc_of("items"))
            return None
        if items[0].level != 0:
            base = min(i.level for i in items)
            items = [ListItem(i.text, i.level - base, i.continuations, i.segments) for i in items]
        ordered = True if b.name == "LIST" and b.get("ordered", False) else False
        if "start" in b and not ordered:
            self.diag.error("ARGUMENT_NOT_APPLICABLE", "Argumen 'start' hanya berlaku untuk daftar berurutan (ordered=true).", b.loc_of("start"))
            return None
        indent = float(b.get("indent", 1.0))
        hanging = float(b.get("hanging", 0.7))
        if hanging > indent:
            self.diag.error(
                "LIST_INDENT_INVALID",
                "hanging tidak boleh lebih besar dari indent (teks item tingkat 0 akan berada di luar margin).",
                b.loc_of("hanging"),
                found=f"indent={indent:g}cm hanging={hanging:g}cm",
            )
            return None
        self._paragraph_count += len(items) + sum(len(i.continuations) for i in items)
        if self._paragraph_count > self.limits.max_paragraphs:
            from ..diagnostics import Diagnostic, FatalDsxError, Severity

            raise FatalDsxError(Diagnostic(Severity.ERROR, "LIMIT_EXCEEDED", f"Jumlah paragraf melebihi batas {self.limits.max_paragraphs}.", b.loc))
        self.used_styles.add(st.name)
        overrides = b.visual_overrides()
        return ListBlock(
            tuple(items), ordered, int(b.get("start", 1)), st.name, overrides, {**st.props, **overrides}, False, b.loc, indent, hanging
        )

    # --------------------------------------------------------------- callout
    def _callout(self, b: BoundCall) -> Callout | None:
        variant = b.get("type", "note")
        if "style" in b:
            selected = self._select_style(b, role="callout")
            if selected is None:
                return None
            body_style = selected[0]
        else:
            body_style = self.registry.get(f"callout-{variant}")
        title_style = self.registry.get("callout-title")
        if body_style is None or title_style is None:
            return None
        raw_text = b.args["text"]
        title_text = collapse_spaces(" ".join(collapse_spaces(l) for l in b.get("title", "").split("\n")))
        theme = CALLOUT_THEMES[variant]
        title = None
        if title_text:
            title = self._make_paragraph(title_text, title_style, "callout", None, {"color": theme["title"]}, b.loc_of("title"))
        overrides = b.visual_overrides()
        body_paras: list[Paragraph] = []
        if isinstance(raw_text, list):
            footnote_seq = [self._footnote_seq]
            segs, plain = raw_to_segments(raw_text, self._footnotes, footnote_seq)
            self._footnote_seq = footnote_seq[0]
            if not plain and not segs and not title_text:
                self.diag.error("EMPTY_CALLOUT", "CALLOUT() membutuhkan teks atau judul yang tidak kosong.", b.loc_of("text"))
                return None
            if not plain and not segs:
                self.diag.warning("EMPTY_TEXT", "Teks CALLOUT() kosong; hanya judul yang ditampilkan.", b.loc_of("text"))
            else:
                body_paras.append(
                    self._make_paragraph(plain, body_style, "callout", None, overrides, b.loc, tuple(segs) if segs else ())
                )
        else:
            parts = split_paragraphs(self._text_value(raw_text), preserve_breaks=False)
            if len(parts) > self.limits.max_callout_paragraphs:
                self.diag.error("LIMIT_EXCEEDED", f"Callout melebihi {self.limits.max_callout_paragraphs} paragraf.", b.loc)
                return None
            if not parts and not title_text:
                self.diag.error("EMPTY_CALLOUT", "CALLOUT() membutuhkan teks atau judul yang tidak kosong.", b.loc_of("text"))
                return None
            if not parts:
                self.diag.warning("EMPTY_TEXT", "Teks CALLOUT() kosong; hanya judul yang ditampilkan.", b.loc_of("text"))
            body_paras = [self._make_paragraph(t, body_style, "callout", None, overrides, b.loc) for t in parts]
        return Callout(variant, title, tuple(body_paras), False, b.loc)

    # ------------------------------------------------------------------ math
    def _math(self, b: BoundCall) -> MathBlock:
        parsed = b.args["expr"]
        st = self.registry.get("equation")
        assert st is not None
        self.used_styles.add(st.name)
        self._paragraph_count += 1
        return MathBlock(
            parsed.source, parsed.tree, b.get("align", "center"), b.get("size"), st.name, {}, dict(st.props), False, b.loc
        )
