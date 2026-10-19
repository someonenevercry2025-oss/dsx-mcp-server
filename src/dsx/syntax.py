"""AST DSX."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from .diagnostics import Location


@dataclass(frozen=True)
class StringLit:
    loc: Location
    value: str


@dataclass(frozen=True)
class NumberLit:
    loc: Location
    value: Union[int, float]


@dataclass(frozen=True)
class QuantityLit:
    loc: Location
    value: Union[int, float]
    unit: str


@dataclass(frozen=True)
class BoolLit:
    loc: Location
    value: bool


@dataclass(frozen=True)
class VarRef:
    loc: Location
    name: str


@dataclass(frozen=True)
class ListLit:
    loc: Location
    items: tuple["Expr", ...]


@dataclass(frozen=True)
class Arg:
    loc: Location
    name: str | None
    value: "Expr"


@dataclass(frozen=True)
class CallExpr:
    loc: Location
    name: str
    args: tuple[Arg, ...]


Expr = Union[StringLit, NumberLit, QuantityLit, BoolLit, VarRef, ListLit, CallExpr]


@dataclass(frozen=True)
class LetStmt:
    loc: Location
    name: str
    value: Expr


@dataclass(frozen=True)
class CallStmt:
    loc: Location
    call: CallExpr


Statement = Union[LetStmt, CallStmt]


@dataclass(frozen=True)
class Program:
    file: str
    statements: tuple[Statement, ...]
