"""Pohon matematika -> Office Math Markup Language (OMML).

Semua elemen dibangun dari pohon semantik tervalidasi; teks pengguna hanya
masuk sebagai isi ``m:t`` (di-escape oleh lxml), tidak pernah sebagai XML mentah.
"""

from __future__ import annotations

from lxml import etree

from ..mathexpr import nodes as mn

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML = "http://www.w3.org/XML/1998/namespace"
MATH_FONT = "Cambria Math"


def _m(tag: str, **attrs: str) -> etree._Element:
    el = etree.Element(f"{{{M}}}{tag}", nsmap={"m": M, "w": W})
    for k, v in attrs.items():
        el.set(f"{{{M}}}{k}", v)
    return el


def _sub(parent: etree._Element, tag: str, **attrs: str) -> etree._Element:
    el = etree.SubElement(parent, f"{{{M}}}{tag}")
    for k, v in attrs.items():
        el.set(f"{{{M}}}{k}", v)
    return el


class OmmlBuilder:
    def __init__(self, size_pt: float | None = None) -> None:
        self.size_pt = size_pt

    # ---------------------------------------------------------------- run
    def run(self, parent: etree._Element, text: str, style: str | None = None, normal: bool = False) -> None:
        r = _sub(parent, "r")
        if style or normal:
            rpr = _sub(r, "rPr")
            if normal:
                _sub(rpr, "nor")
            if style:
                _sub(rpr, "sty", val=style)
        wpr = etree.SubElement(r, f"{{{W}}}rPr")
        fonts = etree.SubElement(wpr, f"{{{W}}}rFonts")
        for attr in ("ascii", "hAnsi", "cs"):
            fonts.set(f"{{{W}}}{attr}", MATH_FONT)
        if self.size_pt is not None:
            sz = etree.SubElement(wpr, f"{{{W}}}sz")
            sz.set(f"{{{W}}}val", str(int(round(self.size_pt * 2))))
        t = _sub(r, "t")
        t.text = text
        if text != text.strip() or "  " in text:
            t.set(f"{{{XML}}}space", "preserve")

    # -------------------------------------------------------------- nodes
    def fill(self, parent: etree._Element, node: mn.Node | None) -> None:
        """Isi ``parent`` (m:e, m:num, dst.) dengan konten ``node``."""
        if node is None:
            return
        if isinstance(node, mn.Row):
            for item in node.items:
                self.fill(parent, item)
        elif isinstance(node, mn.Num):
            self.run(parent, node.text)
        elif isinstance(node, mn.Var):
            self.run(parent, node.text, style="p" if node.upright else None)
        elif isinstance(node, mn.Sym):
            self.run(parent, node.text, style="p")
        elif isinstance(node, mn.Text):
            self.run(parent, node.text, normal=True)
        elif isinstance(node, mn.Frac):
            f = _sub(parent, "f")
            fpr = _sub(f, "fPr")
            _sub(fpr, "type", val="bar")
            self.fill(_sub(f, "num"), node.num)
            self.fill(_sub(f, "den"), node.den)
        elif isinstance(node, mn.Script):
            self.script(parent, node)
        elif isinstance(node, mn.Radical):
            rad = _sub(parent, "rad")
            if node.degree is None:
                rpr = _sub(rad, "radPr")
                _sub(rpr, "degHide", val="1")
                _sub(rad, "deg")
            else:
                self.fill(_sub(rad, "deg"), node.degree)
            self.fill(_sub(rad, "e"), node.arg)
        elif isinstance(node, mn.Delim):
            d = _sub(parent, "d")
            dpr = _sub(d, "dPr")
            _sub(dpr, "begChr", val=node.open)
            _sub(dpr, "endChr", val=node.close)
            self.fill(_sub(d, "e"), node.inner)
        elif isinstance(node, mn.Func):
            self.func(parent, node)
        elif isinstance(node, mn.NAry):
            na = _sub(parent, "nary")
            pr = _sub(na, "naryPr")
            _sub(pr, "chr", val=node.op)
            _sub(pr, "limLoc", val="subSup" if node.op == "∫" else "undOvr")
            if node.lower is None:
                _sub(pr, "subHide", val="1")
            if node.upper is None:
                _sub(pr, "supHide", val="1")
            self.fill(_sub(na, "sub"), node.lower)
            self.fill(_sub(na, "sup"), node.upper)
            self.fill(_sub(na, "e"), node.body)
        else:  # pragma: no cover - dijaga oleh tipe Node
            raise TypeError(f"node matematika tidak dikenal: {type(node).__name__}")

    def script(self, parent: etree._Element, node: mn.Script) -> None:
        if node.sub is not None and node.sup is not None:
            s = _sub(parent, "sSubSup")
        elif node.sup is not None:
            s = _sub(parent, "sSup")
        else:
            s = _sub(parent, "sSub")
        self.fill(_sub(s, "e"), node.base)
        if node.sub is not None:
            self.fill(_sub(s, "sub"), node.sub)
        if node.sup is not None:
            self.fill(_sub(s, "sup"), node.sup)

    def func(self, parent: etree._Element, node: mn.Func) -> None:
        f = _sub(parent, "func")
        fname = _sub(f, "fName")
        holder = fname
        if node.under is not None:
            ll = _sub(fname, "limLow")
            holder = _sub(ll, "e")
        elif node.sub is not None and node.sup is not None:
            s = _sub(fname, "sSubSup"); holder = _sub(s, "e")
        elif node.sup is not None:
            s = _sub(fname, "sSup"); holder = _sub(s, "e")
        elif node.sub is not None:
            s = _sub(fname, "sSub"); holder = _sub(s, "e")
        self.run(holder, node.name, style="p")
        if node.under is not None:
            self.fill(_sub(ll, "lim"), node.under)
        elif node.sub is not None or node.sup is not None:
            if node.sub is not None:
                self.fill(_sub(s, "sub"), node.sub)
            if node.sup is not None:
                self.fill(_sub(s, "sup"), node.sup)
        self.fill(_sub(f, "e"), node.arg)


def build_inline_math(tree: mn.Node, size_pt: float | None = None) -> etree._Element:
    """Bangun ``m:oMath`` (persamaan sebaris) untuk disisipkan di antara run pada ``w:p``."""
    omath = _m("oMath")
    OmmlBuilder(size_pt).fill(omath, tree)
    return omath


def build_math_para(tree: mn.Node, align: str = "center", size_pt: float | None = None) -> etree._Element:
    """Bangun ``m:oMathPara`` (persamaan blok) dari pohon matematika."""
    para = _m("oMathPara")
    ppr = _sub(para, "oMathParaPr")
    _sub(ppr, "jc", val={"left": "left", "center": "center", "right": "right"}[align])
    omath = _sub(para, "oMath")
    OmmlBuilder(size_pt).fill(omath, tree)
    return para
