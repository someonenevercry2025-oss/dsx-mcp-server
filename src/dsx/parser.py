"""Parser recursive descent DSX -> AST.

Tata bahasa (lihat docs/grammar.md):

    program   := statement*
    statement := "LET" IDENT "=" expr | IDENT "(" args? ")"
    args      := arg ("," arg)* ","?
    arg       := (IDENT "=")? expr
    expr      := STRING | NUMBER | "true" | "false" | IDENT | call | list
"""

from __future__ import annotations

from .syntax import (
    Arg,
    BoolLit,
    CallExpr,
    CallStmt,
    Expr,
    LetStmt,
    ListLit,
    NumberLit,
    Program,
    QuantityLit,
    Statement,
    StringLit,
    VarRef,
)
from .diagnostics import Diagnostic, DsxSyntaxError, Severity, make_details
from .lexer import Token, tokenize
from .limits import Limits

_KIND_NAMES = {
    "IDENT": "identifier",
    "STRING": "string",
    "NUMBER": "angka",
    "QUANTITY": "ukuran",
    "LPAREN": "'('",
    "RPAREN": "')'",
    "LBRACKET": "'['",
    "RBRACKET": "']'",
    "COMMA": "','",
    "EQUALS": "'='",
    "EOF": "akhir file",
}


def _describe(tok: Token) -> str:
    if tok.kind == "EOF":
        return "akhir file"
    if tok.kind == "STRING":
        text = str(tok.value)
        if len(text) > 30:
            text = text[:30] + "..."
        return f"string {text!r}"
    return f"{_KIND_NAMES.get(tok.kind, tok.kind)} {tok.value!r}"


class Parser:
    def __init__(self, tokens: list[Token], file: str, limits: Limits) -> None:
        self._tokens = tokens
        self._file = file
        self._limits = limits
        self._pos = 0

    def _peek(self, offset: int = 0) -> Token:
        index = min(self._pos + offset, len(self._tokens) - 1)
        return self._tokens[index]

    def _next(self) -> Token:
        tok = self._tokens[self._pos]
        if tok.kind != "EOF":
            self._pos += 1
        return tok

    def _fail(self, tok: Token, message: str, code: str = "SYNTAX_ERROR") -> DsxSyntaxError:
        return DsxSyntaxError(
            Diagnostic(Severity.ERROR, code, message, tok.loc, make_details(found=_describe(tok)))
        )

    def _expect(self, kind: str, what: str) -> Token:
        tok = self._peek()
        if tok.kind != kind:
            raise self._fail(tok, f"Diharapkan {what}.")
        return self._next()

    def parse(self) -> Program:
        statements: list[Statement] = []
        while self._peek().kind != "EOF":
            statements.append(self._statement())
        return Program(self._file, tuple(statements))

    def _statement(self) -> Statement:
        tok = self._peek()
        if tok.kind != "IDENT":
            raise self._fail(tok, "Diharapkan awal pernyataan (LET atau nama komponen).")
        if tok.value == "LET":
            self._next()
            name_tok = self._expect("IDENT", "nama variabel setelah LET")
            self._expect("EQUALS", "'=' setelah nama variabel")
            value = self._expr(1)
            return LetStmt(tok.loc, str(name_tok.value), value)
        call = self._call(0)
        return CallStmt(tok.loc, call)

    def _call(self, depth: int) -> CallExpr:
        name_tok = self._expect("IDENT", "nama komponen")
        if self._peek().kind != "LPAREN":
            raise self._fail(self._peek(), f"Diharapkan '(' setelah {name_tok.value!r}.")
        self._next()
        args: list[Arg] = []
        seen_keyword = False
        while True:
            tok = self._peek()
            if tok.kind == "RPAREN":
                self._next()
                break
            if tok.kind == "EOF":
                raise self._fail(tok, f"Tanda kurung pada {name_tok.value!r} tidak ditutup.")
            if tok.kind == "IDENT" and self._peek(1).kind == "EQUALS":
                self._next()
                self._next()
                value = self._expr(depth + 1)
                args.append(Arg(tok.loc, str(tok.value), value))
                seen_keyword = True
            else:
                if seen_keyword:
                    raise self._fail(tok, "Argumen posisi tidak boleh muncul setelah argumen bernama.")
                value = self._expr(depth + 1)
                args.append(Arg(tok.loc, None, value))
            nxt = self._peek()
            if nxt.kind == "COMMA":
                self._next()
                continue
            if nxt.kind == "RPAREN":
                self._next()
                break
            raise self._fail(nxt, "Diharapkan ',' atau ')'.")
        return CallExpr(name_tok.loc, str(name_tok.value), tuple(args))

    def _expr(self, depth: int) -> Expr:
        if depth > self._limits.max_nesting_depth:
            raise self._fail(self._peek(), f"Kedalaman sintaks melebihi batas {self._limits.max_nesting_depth}.", "NESTING_TOO_DEEP")
        tok = self._peek()
        if tok.kind == "STRING":
            self._next()
            return StringLit(tok.loc, str(tok.value))
        if tok.kind == "NUMBER":
            self._next()
            return NumberLit(tok.loc, tok.value)  # type: ignore[arg-type]
        if tok.kind == "QUANTITY":
            self._next()
            value, unit = tok.value  # type: ignore[misc]
            return QuantityLit(tok.loc, value, unit)
        if tok.kind == "LBRACKET":
            return self._list(depth)
        if tok.kind == "IDENT":
            if tok.value in ("true", "false"):
                self._next()
                if self._peek().kind == "LPAREN":
                    raise self._fail(self._peek(), f"{tok.value!r} adalah nilai boolean, bukan fungsi.")
                return BoolLit(tok.loc, tok.value == "true")
            if self._peek(1).kind == "LPAREN":
                return self._call(depth)
            self._next()
            return VarRef(tok.loc, str(tok.value))
        raise self._fail(tok, "Diharapkan sebuah nilai (string, angka, true/false, list, variabel, atau fungsi).")

    def _list(self, depth: int) -> ListLit:
        start = self._expect("LBRACKET", "'['")
        items: list[Expr] = []
        while True:
            tok = self._peek()
            if tok.kind == "RBRACKET":
                self._next()
                break
            if tok.kind == "EOF":
                raise self._fail(tok, "List tidak ditutup dengan ']'.")
            items.append(self._expr(depth + 1))
            nxt = self._peek()
            if nxt.kind == "COMMA":
                self._next()
                continue
            if nxt.kind == "RBRACKET":
                self._next()
                break
            raise self._fail(nxt, "Diharapkan ',' atau ']'.")
        return ListLit(start.loc, tuple(items))


def parse(source: str, file: str = "document.dsx", limits: Limits | None = None) -> Program:
    limits = limits or Limits()
    tokens = tokenize(source, file, limits)
    return Parser(tokens, file, limits).parse()
