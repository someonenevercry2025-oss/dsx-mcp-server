"""Inspektur struktural untuk keluaran DOCX (Blueprint XI.4)."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from ..ir.nodes import DocumentIR, Figure
from .omml_validator import validate_omml

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS = {"w": W, "r": R, "a": A, "wp": WP}
_MAX_PART_BYTES = 200_000_000


@dataclass
class InspectionReport:
    ok: bool
    problems: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _parse(data: bytes) -> Any:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    return etree.fromstring(data, parser)


def _paragraph_text(p: Any) -> str:
    out: list[str] = []
    for node in p.iter():
        if node.tag == _q(W, "t"):
            out.append(node.text or "")
        elif node.tag == _q(W, "br") and node.get(_q(W, "type")) in (None, "textWrapping"):
            out.append("\n")
        elif node.tag == _q(W, "tab"):
            out.append("\t")
    return "".join(out)


def inspect_docx(data: bytes, ir: DocumentIR | None = None) -> InspectionReport:
    problems: list[str] = []
    stats: dict[str, Any] = {}
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return InspectionReport(False, ["Berkas bukan paket ZIP/DOCX yang valid."])
    with archive:
        names = set(archive.namelist())
        for required in ("[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml"):
            if required not in names:
                problems.append(f"Bagian paket wajib tidak ada: {required}")
        if problems:
            return InspectionReport(False, problems)
        total = sum(i.file_size for i in archive.infolist())
        if total > _MAX_PART_BYTES:
            return InspectionReport(False, ["Ukuran paket terdekompresi tidak wajar."])
        parts: dict[str, Any] = {}
        for name in sorted(names):
            if name.endswith(".xml") or name.endswith(".rels"):
                try:
                    parts[name] = _parse(archive.read(name))
                except etree.XMLSyntaxError as exc:
                    problems.append(f"XML tidak valid pada {name}: {exc}")
        if problems:
            return InspectionReport(False, problems)
        document = parts["word/document.xml"]
        styles = parts["word/styles.xml"]
        style_ids = {s.get(_q(W, "styleId")) for s in styles.findall(_q(W, "style"))}

        # style yang dirujuk harus tersedia
        for name, root in parts.items():
            if not name.startswith("word/"):
                continue
            for tag in ("pStyle", "tblStyle", "rStyle"):
                for node in root.iter(_q(W, tag)):
                    sid = node.get(_q(W, "val"))
                    if sid not in style_ids:
                        problems.append(f"Style {sid!r} dirujuk pada {name} tetapi tidak didefinisikan.")

        # definisi penomoran: abstractNum harus mendahului num; num harus merujuk abstractNum yang ada
        numbering_formats: dict[str, str] = {}
        numbering = parts.get("word/numbering.xml")
        if numbering is not None:
            kids = [c.tag for c in numbering if isinstance(c.tag, str)]
            first_num = kids.index(_q(W, "num")) if _q(W, "num") in kids else len(kids)
            if _q(W, "abstractNum") in kids[first_num:]:
                problems.append("Urutan numbering.xml tidak valid: abstractNum muncul setelah num.")
            abstract_fmt: dict[str, str] = {}
            for node in numbering.findall(_q(W, "abstractNum")):
                lvl0 = node.find(f"{_q(W, 'lvl')}/{_q(W, 'numFmt')}")
                abstract_fmt[node.get(_q(W, "abstractNumId"))] = lvl0.get(_q(W, "val")) if lvl0 is not None else ""
            for node in numbering.findall(_q(W, "num")):
                ref = node.find(_q(W, "abstractNumId"))
                aid = ref.get(_q(W, "val")) if ref is not None else None
                if aid not in abstract_fmt:
                    problems.append(f"w:num {node.get(_q(W, 'numId'))} merujuk abstractNum {aid!r} yang tidak ada.")
                else:
                    numbering_formats[node.get(_q(W, "numId"))] = abstract_fmt[aid]
        # urutan struktur body
        body = document.find(_q(W, "body"))
        actual: list[tuple] = []
        inline_math = 0
        previous_was_table = False
        if body is None:
            problems.append("Elemen body tidak ditemukan.")
            body = etree.Element(_q(W, "body"))
        for child in body:
            if child.tag == _q(W, "p"):
                text = _paragraph_text(child)
                has_drawing = child.find(".//" + _q(W, "drawing")) is not None
                outline = child.find(f"{_q(W, 'pPr')}/{_q(W, 'outlineLvl')}")
                level = int(outline.get(_q(W, "val"))) + 1 if outline is not None else None
                for inline in child.findall(_q(M, "oMath")):
                    inline_math += 1
                    for issue in validate_omml(inline):
                        problems.append(f"Persamaan sebaris tidak valid: {issue}")
                math_para = child.find(_q(M, "oMathPara"))
                num_pr = child.find(f"{_q(W, 'pPr')}/{_q(W, 'numPr')}")
                if math_para is not None:
                    for issue in validate_omml(math_para):
                        problems.append(f"Persamaan tidak valid: {issue}")
                    actual.append(("math",))
                elif num_pr is not None:
                    ilvl = num_pr.find(_q(W, "ilvl"))
                    num_id = num_pr.find(_q(W, "numId"))
                    li_level = int(ilvl.get(_q(W, "val"))) if ilvl is not None else 0
                    nid = num_id.get(_q(W, "val")) if num_id is not None else None
                    if not 0 <= li_level <= 8:
                        problems.append(f"Level daftar di luar rentang 0-8: {li_level}")
                    if nid not in numbering_formats:
                        problems.append(f"Item daftar merujuk numId {nid!r} yang tidak didefinisikan.")
                    actual.append(("li", text, li_level, numbering_formats.get(nid) not in (None, "bullet")))
                elif has_drawing:
                    actual.append(("figure",))
                elif previous_was_table and text == "":
                    actual.append(("spacer",))
                else:
                    actual.append(("p", text, level))
                previous_was_table = False
            elif child.tag == _q(W, "tbl"):
                rows = child.findall(_q(W, "tr"))
                widths = {len(r.findall(_q(W, "tc"))) for r in rows}
                if len(widths) > 1:
                    problems.append("Tabel memiliki jumlah sel yang tidak seragam antar baris.")
                caption = child.find(f"{_q(W, 'tblPr')}/{_q(W, 'tblCaption')}")
                tag = caption.get(_q(W, "val")) if caption is not None else ""
                if tag.startswith("dsx-callout:"):
                    cells = child.findall(f"{_q(W, 'tr')}/{_q(W, 'tc')}")
                    if len(rows) != 1 or len(cells) != 1:
                        problems.append("Callout harus berupa tabel satu sel.")
                    paras = cells[0].findall(_q(W, "p")) if cells else []
                    if cells and cells[0].find(f"{_q(W, 'tcPr')}/{_q(W, 'shd')}") is None:
                        problems.append("Callout tidak memiliki shading.")
                    actual.append(("callout", tag.split(":", 1)[1], len(paras)))
                else:
                    actual.append(("tbl", len(rows), max(widths) if widths else 0))
                previous_was_table = True
            elif child.tag == _q(W, "sectPr"):
                if child.find(_q(W, "pgSz")) is None or child.find(_q(W, "pgMar")) is None:
                    problems.append("Properti halaman (pgSz/pgMar) tidak lengkap.")
        stats["body_elements"] = len(actual)
        stats["headings"] = sum(1 for e in actual if e[0] == "p" and e[2] is not None)
        stats["tables"] = sum(1 for e in actual if e[0] == "tbl")
        stats["figures"] = sum(1 for e in actual if e[0] == "figure")
        stats["list_items"] = sum(1 for e in actual if e[0] == "li")
        stats["callouts"] = sum(1 for e in actual if e[0] == "callout")
        stats["equations"] = sum(1 for e in actual if e[0] == "math")
        # Semua oMath di pohon dokumen (paragraf, sel tabel, callout)
        inline_math = sum(1 for _ in document.iter(_q(M, "oMath")))
        # oMath di dalam oMathPara dihitung sebagai persamaan blok, bukan sebaris
        for para in document.iter(_q(M, "oMathPara")):
            inline_math -= len(para.findall(_q(M, "oMath")))
        stats["inline_equations"] = max(0, inline_math)

        # gambar
        rels = parts.get("word/_rels/document.xml.rels")
        rel_targets: dict[str, str] = {}
        if rels is not None:
            for rel in rels.findall(_q(REL, "Relationship")):
                rel_targets[rel.get("Id")] = rel.get("Target")
        doc_ids: list[str] = []
        for blip in document.iter(_q(A, "blip")):
            rid = blip.get(_q(R, "embed"))
            target = rel_targets.get(rid)
            if target is None:
                problems.append(f"Referensi gambar {rid!r} tidak memiliki relasi.")
                continue
            path = "word/" + target if not target.startswith("/") else target.lstrip("/")
            if path not in names:
                problems.append(f"Berkas gambar {path!r} tidak ada dalam paket.")
        for node in document.iter(_q(WP, "docPr")):
            doc_ids.append(node.get("id"))
        if len(doc_ids) != len(set(doc_ids)):
            problems.append("ID docPr gambar tidak unik.")

        # bandingkan dengan IR
        if ir is not None:
            expected = ir.expected_structure()
            if len(expected) != len(actual):
                problems.append(f"Jumlah elemen body {len(actual)} tidak sama dengan yang diharapkan {len(expected)}.")
            else:
                for index, (exp, act) in enumerate(zip(expected, actual)):
                    if exp != act:
                        problems.append(f"Elemen body #{index + 1} berbeda: diharapkan {exp!r}, ditemukan {act!r}.")
                        if len(problems) > 20:
                            break
            if inline_math != ir.inline_math_count():
                problems.append(f"Jumlah persamaan sebaris {inline_math} tidak sama dengan IR ({ir.inline_math_count()}).")
            figures = sum(1 for b in ir.blocks if isinstance(b, Figure))
            if figures != stats["figures"]:
                problems.append("Jumlah gambar tidak sesuai dengan IR.")
            core = parts.get("docProps/core.xml")
            if core is not None:
                title = core.find("{http://purl.org/dc/elements/1.1/}title")
                actual_title = (title.text or "") if title is not None else ""
                if actual_title != ir.metadata.title:
                    problems.append("Judul pada metadata dokumen tidak sesuai.")
            # header/footer
            wanted = []
            if ir.header is not None:
                wanted.append(("header", ir.header.text))
            if ir.footer is not None:
                wanted.append(("footer", ir.footer.text))
            for kind, text in wanted:
                texts = [
                    "".join(t.text or "" for t in root.iter(_q(W, "t")))
                    for name, root in parts.items()
                    if name.startswith(f"word/{kind}") and name.endswith(".xml")
                ]
                if not any(text in t for t in texts):
                    problems.append(f"Teks {kind} tidak ditemukan pada paket.")
            if ir.page_number is not None:
                found = any(
                    (node.text or "").strip().startswith(("PAGE", "NUMPAGES"))
                    for name, root in parts.items()
                    if name.startswith("word/header") or name.startswith("word/footer")
                    for node in root.iter(_q(W, "instrText"))
                )
                if not found:
                    problems.append("Field nomor halaman tidak ditemukan pada header/footer.")

    # buka ulang dengan python-docx
    try:
        from docx import Document

        Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - laporan kegagalan pembukaan
        problems.append(f"python-docx gagal membuka dokumen: {exc}")
    return InspectionReport(not problems, problems, stats)
