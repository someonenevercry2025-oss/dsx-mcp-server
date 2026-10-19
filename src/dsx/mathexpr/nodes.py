"""Pohon semantik matematika yang tidak bergantung pada format keluaran."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class Num:
    text: str


@dataclass(frozen=True)
class Var:
    """Variabel (dirender miring); ``upright`` untuk huruf kapital Yunani, dll."""

    text: str
    upright: bool = False


@dataclass(frozen=True)
class Sym:
    """Operator, relasi, atau simbol (selalu tegak)."""

    text: str


@dataclass(frozen=True)
class Text:
    """Teks biasa di dalam persamaan (mis. text('kecepatan'))."""

    text: str


@dataclass(frozen=True)
class Row:
    items: tuple["Node", ...]


@dataclass(frozen=True)
class Frac:
    num: "Node"
    den: "Node"


@dataclass(frozen=True)
class Script:
    """Pangkat dan/atau indeks. Minimal salah satu dari sub/sup terisi."""

    base: "Node"
    sub: "Node | None" = None
    sup: "Node | None" = None


@dataclass(frozen=True)
class Radical:
    arg: "Node"
    degree: "Node | None" = None


@dataclass(frozen=True)
class Delim:
    open: str
    close: str
    inner: "Node"


@dataclass(frozen=True)
class Func:
    """Fungsi bernama (sin, log, lim, ...). ``sub``/``sup`` menempel pada nama; ``under`` untuk lim."""

    name: str
    arg: "Node | None" = None
    sub: "Node | None" = None
    sup: "Node | None" = None
    under: "Node | None" = None


@dataclass(frozen=True)
class NAry:
    """Operator besar: sum, prod, int."""

    op: str
    lower: "Node | None"
    upper: "Node | None"
    body: "Node"


Node = Union[Num, Var, Sym, Text, Row, Frac, Script, Radical, Delim, Func, NAry]


def plain_text(node: Node | None) -> str:
    """Representasi teks datar (untuk diagnostik/pemeriksaan, bukan untuk tampilan)."""
    if node is None:
        return ""
    if isinstance(node, (Num, Var, Sym, Text)):
        return node.text
    if isinstance(node, Row):
        return "".join(plain_text(i) for i in node.items)
    if isinstance(node, Frac):
        return f"({plain_text(node.num)})/({plain_text(node.den)})"
    if isinstance(node, Script):
        out = plain_text(node.base)
        if node.sub is not None:
            out += "_" + plain_text(node.sub)
        if node.sup is not None:
            out += "^" + plain_text(node.sup)
        return out
    if isinstance(node, Radical):
        return f"√({plain_text(node.arg)})"
    if isinstance(node, Delim):
        return node.open + plain_text(node.inner) + node.close
    if isinstance(node, Func):
        return node.name + plain_text(node.arg)
    if isinstance(node, NAry):
        return node.op + plain_text(node.body)
    raise TypeError(type(node).__name__)  # pragma: no cover
