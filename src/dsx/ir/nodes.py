"""Document IR: representasi dokumen yang sudah divalidasi dan bebas sintaks DSX."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union

from ..diagnostics import Location
from ..mathexpr import Node as MathNode
from ..styles.registry import ResolvedStyle


@dataclass(frozen=True)
class Metadata:
    title: str = ""
    author: str = ""
    subject: str = ""
    template: str = "default"
    language: str | None = None


@dataclass(frozen=True)
class PageConfig:
    size_name: str
    orientation: str
    width_cm: float
    height_cm: float
    margin_top: float
    margin_bottom: float
    margin_left: float
    margin_right: float

    @property
    def content_width(self) -> float:
        return self.width_cm - self.margin_left - self.margin_right

    @property
    def content_height(self) -> float:
        return self.height_cm - self.margin_top - self.margin_bottom


@dataclass(frozen=True)
class TextSeg:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass(frozen=True)
class MathSeg:
    """Persamaan sebaris di dalam alur paragraf."""

    expression: str
    tree: MathNode


@dataclass(frozen=True)
class LinkSeg:
    """Hyperlink sebaris."""

    text: str
    url: str
    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass(frozen=True)
class FootnoteSeg:
    """Tanda referensi catatan kaki di dalam alur paragraf."""

    note_id: int  # 1-based
    text: str  # isi catatan


Segment = Union[TextSeg, MathSeg, LinkSeg, FootnoteSeg]


@dataclass(frozen=True)
class TocBlock:
    """Daftar isi (field TOC Word)."""

    title: str
    depth: int
    page_break_before: bool = False
    source: Location | None = None


@dataclass(frozen=True)
class FootnoteDef:
    """Definisi catatan kaki (disimpan di DocumentIR)."""

    note_id: int
    text: str


@dataclass(frozen=True)
class Paragraph:
    text: str  # teks polos; pada paragraf bersegmen hanya gabungan segmen teks (tanpa matematika)
    role: str
    level: int | None
    style: str
    overrides: dict[str, Any] = field(default_factory=dict)
    effective: dict[str, Any] = field(default_factory=dict)
    source: Location | None = None
    segments: tuple[Segment, ...] = ()  # terisi hanya bila paragraf memuat matematika sebaris

    @property
    def is_heading(self) -> bool:
        return self.role == "heading"


@dataclass(frozen=True)
class TextBlock:
    paragraphs: tuple[Paragraph, ...]
    source: Location | None = None


@dataclass(frozen=True)
class ImageAsset:
    path: str
    data: bytes
    content_type: str


@dataclass(frozen=True)
class Figure:
    image: ImageAsset
    width_cm: float
    height_cm: float
    align: str
    alt: str
    caption: Paragraph | None
    page_break_before: bool = False
    source: Location | None = None


@dataclass(frozen=True)
class TableCell:
    """Isi sel: teks polos atau segmen kaya."""
    text: str
    segments: tuple = ()  # Segment... opsional


@dataclass(frozen=True)
class Table:
    header: tuple[TableCell, ...] | None
    rows: tuple[tuple[TableCell, ...], ...]
    align: str
    caption: Paragraph | None
    page_break_before: bool = False
    source: Location | None = None

    @property
    def column_count(self) -> int:
        if self.header is not None:
            return len(self.header)
        return len(self.rows[0]) if self.rows else 0

    @property
    def row_count(self) -> int:
        return len(self.rows) + (1 if self.header is not None else 0)


@dataclass(frozen=True)
class HeaderFooter:
    text: str
    style: str
    overrides: dict[str, Any]


@dataclass(frozen=True)
class PageNumber:
    position: str
    format: str
    style: str
    overrides: dict[str, Any]


@dataclass(frozen=True)
class ListItem:
    text: str  # plain fallback / expected_structure
    level: int  # 0 = tingkat teratas
    continuations: tuple[str, ...] = ()  # paragraf lanjutan plain (tanpa nomor/bullet)
    segments: tuple = ()  # Segment... bila item memuat format sebaris / IMATH


@dataclass(frozen=True)
class ListBlock:
    items: tuple[ListItem, ...]
    ordered: bool
    start: int
    style: str
    overrides: dict[str, Any]
    effective: dict[str, Any]
    page_break_before: bool = False
    source: Location | None = None
    indent_cm: float = 1.0  # tambahan indentasi kiri per tingkat
    hanging_cm: float = 0.7  # lebar area nomor/bullet


@dataclass(frozen=True)
class Callout:
    variant: str
    title: Paragraph | None
    body: tuple[Paragraph, ...]
    page_break_before: bool = False
    source: Location | None = None


@dataclass(frozen=True)
class MathBlock:
    expression: str
    tree: MathNode
    align: str
    size: float | None
    style: str
    overrides: dict[str, Any]
    effective: dict[str, Any]
    page_break_before: bool = False
    source: Location | None = None


Block = Union[Paragraph, TextBlock, Figure, Table, ListBlock, Callout, MathBlock, TocBlock]


@dataclass(frozen=True)
class DocumentIR:
    metadata: Metadata
    page: PageConfig
    styles: dict[str, ResolvedStyle]
    blocks: tuple[Block, ...]
    header: HeaderFooter | None = None
    footer: HeaderFooter | None = None
    page_number: PageNumber | None = None
    footnotes: tuple[FootnoteDef, ...] = ()
    source_name: str = "document.dsx"

    def iter_paragraphs(self):
        for block in self.blocks:
            if isinstance(block, Paragraph):
                yield block
            elif isinstance(block, TextBlock):
                yield from block.paragraphs
            elif isinstance(block, Figure) and block.caption is not None:
                yield block.caption
            elif isinstance(block, Table) and block.caption is not None:
                yield block.caption
            elif isinstance(block, Callout):
                if block.title is not None:
                    yield block.title
                yield from block.body

    def expected_structure(self) -> list[tuple]:
        """Urutan elemen body yang diharapkan pada keluaran DOCX.

        Aturan renderer: caption tabel di atas tabel, caption gambar di bawah
        gambar, dan satu paragraf pemisah kosong setelah setiap tabel.
        """
        out: list[tuple] = []
        for block in self.blocks:
            if isinstance(block, Paragraph):
                text = block.text
                if block.segments:
                    parts = []
                    for s in block.segments:
                        if isinstance(s, TextSeg):
                            parts.append(s.text)
                        elif isinstance(s, LinkSeg):
                            parts.append(s.text)
                        elif isinstance(s, FootnoteSeg):
                            parts.append(f"[{s.note_id}]")
                        # MathSeg: no plain text contribution
                    text = "".join(parts)
                out.append(("p", text, block.level if block.is_heading else None))
            elif isinstance(block, TextBlock):
                for p in block.paragraphs:
                    out.append(("p", p.text, p.level if p.is_heading else None))
            elif isinstance(block, Figure):
                out.append(("figure",))
                if block.caption is not None:
                    out.append(("p", block.caption.text, None))
            elif isinstance(block, Table):
                if block.caption is not None:
                    out.append(("p", block.caption.text, None))
                out.append(("tbl", block.row_count, block.column_count))
                out.append(("spacer",))
            elif isinstance(block, ListBlock):
                for item in block.items:
                    out.append(("li", item.text, item.level, block.ordered))
                    for extra in item.continuations:
                        out.append(("p", extra, None))
            elif isinstance(block, Callout):
                count = len(block.body) + (1 if block.title is not None else 0)
                out.append(("callout", block.variant, count))
                out.append(("spacer",))
            elif isinstance(block, MathBlock):
                out.append(("math",))
            elif isinstance(block, TocBlock):
                if block.title:
                    out.append(("p", block.title, None))
                out.append(("p", "(Daftar isi — perbarui field di Word/LibreOffice)", None))
                out.append(("p", "", None))  # spacer rendered as empty paragraph
        if self.footnotes:
            out.append(("p", "─" * 24, None))
            out.append(("p", "Catatan kaki", None))
            for fn in self.footnotes:
                out.append(("p", f"[{fn.note_id}] {fn.text}", None))
        if not out:
            out.append(("p", "", None))  # dokumen kosong dirender dengan satu paragraf kosong
        return out

    def inline_math_count(self) -> int:
        n = sum(1 for p in self.iter_paragraphs() for s in p.segments if isinstance(s, MathSeg))
        for block in self.blocks:
            if isinstance(block, ListBlock):
                for item in block.items:
                    n += sum(1 for s in item.segments if isinstance(s, MathSeg))
            elif isinstance(block, Table):
                cells = []
                if block.header:
                    cells.extend(block.header)
                for row in block.rows:
                    cells.extend(row)
                n += sum(1 for c in cells for s in c.segments if isinstance(s, MathSeg))
        return n

    def summary(self) -> dict[str, int]:
        paragraphs = list(self.iter_paragraphs())
        return {
            "paragraphs": len(paragraphs),
            "headings": sum(1 for p in paragraphs if p.is_heading),
            "figures": sum(1 for b in self.blocks if isinstance(b, Figure)),
            "tables": sum(1 for b in self.blocks if isinstance(b, Table)),
            "lists": sum(1 for b in self.blocks if isinstance(b, ListBlock)),
            "list_items": sum(len(b.items) for b in self.blocks if isinstance(b, ListBlock)),
            "callouts": sum(1 for b in self.blocks if isinstance(b, Callout)),
            "equations": sum(1 for b in self.blocks if isinstance(b, MathBlock)),
            "inline_equations": self.inline_math_count(),
            "tocs": sum(1 for b in self.blocks if isinstance(b, TocBlock)),
            "footnotes": len(self.footnotes),
            "styles": len(self.styles),
        }
