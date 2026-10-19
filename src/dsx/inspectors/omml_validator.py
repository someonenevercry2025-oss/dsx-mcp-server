"""Pemeriksa struktur OMML untuk subset yang dihasilkan DSX.

Memeriksa nama elemen, anak yang diizinkan, dan urutannya per elemen (mengikuti
CT_* pada skema ECMA-376 Math). Ini pemeriksaan struktural, bukan pengganti
membuka dokumen di Microsoft Word.
"""

from __future__ import annotations

from lxml import etree

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MAX_DEPTH = 200

CONTENT = ("r", "f", "sSup", "sSub", "sSubSup", "rad", "d", "func", "nary", "limLow")
# elemen -> urutan anak yang diizinkan; "*" di akhir nama = boleh berulang/opsional
SEQUENCE: dict[str, tuple[str, ...]] = {
    "oMathPara": ("oMathParaPr", "oMath"),
    "oMathParaPr": ("jc",),
    "f": ("fPr", "num", "den"),
    "fPr": ("type",),
    "sSup": ("sSupPr", "e", "sup"),
    "sSub": ("sSubPr", "e", "sub"),
    "sSubSup": ("sSubSupPr", "e", "sub", "sup"),
    "rad": ("radPr", "deg", "e"),
    "radPr": ("degHide",),
    "d": ("dPr", "e"),
    "dPr": ("begChr", "endChr"),
    "func": ("funcPr", "fName", "e"),
    "nary": ("naryPr", "sub", "sup", "e"),
    "naryPr": ("chr", "limLoc", "subHide", "supHide"),
    "limLow": ("limLowPr", "e", "lim"),
    "r": ("rPr", "rPr_w", "t"),
    "rPr": ("nor", "sty"),
}
REQUIRED: dict[str, tuple[str, ...]] = {
    "oMathPara": ("oMath",),
    "f": ("num", "den"),
    "sSup": ("e", "sup"),
    "sSub": ("e", "sub"),
    "sSubSup": ("e", "sub", "sup"),
    "rad": ("deg", "e"),
    "d": ("e",),
    "func": ("fName", "e"),
    "nary": ("sub", "sup", "e"),
    "limLow": ("e", "lim"),
    "r": ("t",),
}
CONTAINERS = ("oMath", "e", "num", "den", "sub", "sup", "deg", "fName", "lim")
LEAF_ATTR = ("jc", "type", "degHide", "begChr", "endChr", "chr", "limLoc", "subHide", "supHide", "nor", "sty")
ATTR_VALUES = {
    "jc": {"left", "center", "right", "centerGroup"},
    "type": {"bar", "skw", "lin", "noBar"},
    "limLoc": {"undOvr", "subSup"},
    "sty": {"p", "b", "i", "bi"},
    "degHide": {"0", "1"},
    "subHide": {"0", "1"},
    "supHide": {"0", "1"},
}


def _q(tag: str) -> str:
    return f"{{{M}}}{tag}"


def _name(el: etree._Element) -> str | None:
    if not isinstance(el.tag, str):
        return None
    ns, _, local = el.tag[1:].partition("}")
    if ns == M:
        return local
    if ns == W and local == "rPr":
        return "rPr_w"
    return f"?{el.tag}"


def validate_omml(root: etree._Element) -> list[str]:
    """Kembalikan daftar masalah (kosong bila struktur valid)."""
    problems: list[str] = []
    if root.tag == _q("oMath"):
        _check(root, "oMath", 0, problems)
        return problems
    if root.tag != _q("oMathPara"):
        return [f"Akar harus m:oMathPara atau m:oMath, ditemukan {root.tag}"]
    _check(root, "oMathPara", 0, problems)
    return problems


def _check(el: etree._Element, name: str, depth: int, problems: list[str]) -> None:
    if depth > _MAX_DEPTH:
        problems.append("Kedalaman OMML tidak wajar.")
        return
    kids = [(k, _name(k)) for k in el if isinstance(k.tag, str)]
    names = [n for _, n in kids]
    if name in CONTAINERS:
        for k, n in kids:
            if n not in CONTENT:
                problems.append(f"m:{name} tidak boleh memuat {n!r}.")
            else:
                _check(k, n, depth + 1, problems)
        return
    if name in LEAF_ATTR:
        if kids:
            problems.append(f"m:{name} tidak boleh memiliki anak.")
        val = el.get(_q("val"))
        if name in ("begChr", "endChr", "chr"):
            if not val:
                problems.append(f"m:{name} membutuhkan m:val.")
        elif name in ATTR_VALUES and val not in ATTR_VALUES[name]:
            problems.append(f"m:{name} bernilai tidak valid: {val!r}.")
        elif name in ("nor",):
            pass
        return
    if name == "t":
        if kids:
            problems.append("m:t tidak boleh memiliki elemen anak.")
        return
    if name == "rPr_w":
        return
    allowed = SEQUENCE.get(name)
    if allowed is None:
        problems.append(f"Elemen tidak dikenal: {name}")
        return
    last = -1
    for k, n in kids:
        if n not in allowed:
            problems.append(f"m:{name} tidak boleh memuat {n!r}.")
            continue
        idx = allowed.index(n)
        if idx < last or (idx == last and n != "e"):
            problems.append(f"Urutan anak m:{name} salah pada {n!r}.")
        last = max(last, idx)
        _check(k, n, depth + 1, problems)
    for needed in REQUIRED.get(name, ()):
        if needed not in names:
            problems.append(f"m:{name} tidak memiliki anak wajib m:{needed}.")
    if name == "r":
        t = el.find(_q("t"))
        if t is not None and (t.text or "") == "":
            problems.append("m:r memiliki m:t kosong.")
