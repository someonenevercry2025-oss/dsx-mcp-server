"""Parser DSX-Math.

Sintaks linear terbatas. Rangkuman (lengkap: docs/math.md):

  angka          3  3.14
  variabel       x  (deretan huruf dipecah: ``ac`` = a c; nama dikenal utuh)
  operator       + - * = < > <= >= != ~= -> => +- ... dan Unicode (± × ≤ ≥ ≠ ∞ ...)
  pangkat        x^2   x^(n+1)   x^-1        indeks   x_i   x_(i+1)   x_i^2
  pecahan        a/b   (a+b)/(c+d)   frac(a, b)    ("/" mengikat atom terdekat)
  akar           sqrt(x)   root(n, x)          mutlak  abs(x)   norm(x)
  fungsi         sin cos tan log ln exp ... (sin x, sin(x), sin^2 x, log_2 x)
  operator besar sum(i=1, n, i^2)   prod(...)   int(a, b, f(x) dx)   lim(x->0, f(x))
  teks           text('kecepatan')  atau  'kecepatan'
  nama           alpha ... omega, Gamma ... Omega, infty, times, cdot, pm, leq, ...

Tidak didukung (ditolak dengan diagnostic, tidak diabaikan diam-diam): LaTeX
(backslash), matriks, aksen, lingkungan multi-baris, ``{ }`` sebagai pengelompok.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from ..limits import Limits
from .nodes import Delim, Frac, Func, NAry, Node, Num, Radical, Row, Script, Sym, Text, Var

GREEK_LOWER = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "omicron": "ο", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "chi": "χ", "psi": "ψ", "omega": "ω",
}
GREEK_UPPER = {
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
WORD_SYMBOLS = {
    "infty": "∞", "inf": "∞", "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓",
    "neq": "≠", "leq": "≤", "geq": "≥", "approx": "≈", "equiv": "≡", "propto": "∝",
    "to": "→", "rightarrow": "→", "leftarrow": "←", "Rightarrow": "⇒", "Leftrightarrow": "⇔",
    "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆", "cup": "∪", "cap": "∩",
    "forall": "∀", "exists": "∃", "partial": "∂", "nabla": "∇", "degree": "°", "ldots": "…",
    "cdots": "⋯", "angle": "∠", "perp": "⊥", "parallel": "∥",
}
FUNCTIONS = (
    "sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh log ln exp min max det gcd mod".split()
)
COMMANDS = {"sqrt", "root", "frac", "abs", "norm", "sum", "prod", "int", "lim", "text"}
KNOWN_WORDS = set(GREEK_LOWER) | set(GREEK_UPPER) | set(WORD_SYMBOLS) | set(FUNCTIONS) | COMMANDS
NARY_CHARS = {"sum": "∑", "prod": "∏", "int": "∫"}
# operator ASCII (urut dari yang terpanjang)
MULTI_OPS = [
    ("<=>", "⇔"), ("+-", "±"), ("-+", "∓"), ("<=", "≤"), (">=", "≥"), ("!=", "≠"), ("~=", "≈"),
    ("->", "→"), ("<-", "←"), ("=>", "⇒"),
]
SINGLE_SYMS = {
    "+": "+", "-": "−", "*": "·", "=": "=", "<": "<", ">": ">", ":": ":", ",": ",",
    ".": ".", "|": "|", "%": "%", "~": "~",
}
OPEN = {"(": ")", "[": "]", "{": "}"}
CLOSE = set(OPEN.values())
_FORBIDDEN_HINT = {
    "\\": "Sintaks LaTeX (backslash) tidak didukung; gunakan DSX-Math, mis. sqrt(x), frac(a, b), alpha.",
    "@": "Karakter '@' tidak didukung.",
    "#": "Karakter '#' tidak didukung.",
    "$": "Karakter '$' tidak didukung.",
    "&": "Karakter '&' tidak didukung (tidak ada lingkungan multi-baris/matriks).",
    ";": "Karakter ';' tidak didukung.",
    '"': "Gunakan tanda kutip tunggal 'teks' untuk teks biasa di dalam persamaan.",
    "`": "Karakter '`' tidak didukung.",
    "?": "Karakter '?' tidak didukung.",
}


class MathSyntaxError(ValueError):
    def __init__(self, message: str, position: int) -> None:
        super().__init__(message)
        self.message = message
        self.position = position  # indeks karakter (0-based)


@dataclass(frozen=True)
class ParsedMath:
    source: str
    tree: Node
    node_count: int


@dataclass(frozen=True)
class _Tok:
    kind: str  # NUM WORD VAR SYM STR OPEN CLOSE EOF
    value: str
    pos: int


def _tokenize(src: str) -> list[_Tok]:
    toks: list[_Tok] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\n":
            i += 1
            continue
        if "0" <= ch <= "9":
            j = i
            while j < n and "0" <= src[j] <= "9":
                j += 1
            if j + 1 < n and src[j] == "." and "0" <= src[j + 1] <= "9":
                j += 1
                while j < n and "0" <= src[j] <= "9":
                    j += 1
            toks.append(_Tok("NUM", src[i:j], i))
            i = j
            continue
        if ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            j = i
            while j < n and (("a" <= src[j] <= "z") or ("A" <= src[j] <= "Z")):
                j += 1
            run = src[i:j]
            if run in KNOWN_WORDS:
                toks.append(_Tok("WORD", run, i))
            else:
                for k, letter in enumerate(run):
                    toks.append(_Tok("VAR", letter, i + k))
            i = j
            continue
        if ch == "'":
            j = src.find("'", i + 1)
            if j == -1:
                raise MathSyntaxError("Teks dengan tanda kutip tunggal tidak ditutup.", i)
            toks.append(_Tok("STR", src[i + 1 : j], i))
            i = j + 1
            continue
        matched = False
        for op, sym in MULTI_OPS:
            if src.startswith(op, i):
                toks.append(_Tok("SYM", sym, i))
                i += len(op)
                matched = True
                break
        if matched:
            continue
        if ch in OPEN:
            toks.append(_Tok("OPEN", ch, i))
        elif ch in CLOSE:
            toks.append(_Tok("CLOSE", ch, i))
        elif ch in ("^", "_", "/", "!"):
            toks.append(_Tok("SYM", ch, i))
        elif ch in SINGLE_SYMS:
            toks.append(_Tok("SYM", SINGLE_SYMS[ch], i))
        elif ord(ch) < 128:
            raise MathSyntaxError(_FORBIDDEN_HINT.get(ch, f"Karakter {ch!r} tidak didukung dalam ekspresi matematika."), i)
        else:
            cat = unicodedata.category(ch)
            if cat.startswith("L"):
                toks.append(_Tok("VAR", ch, i))
            elif cat.startswith("N"):
                toks.append(_Tok("NUM", ch, i))
            elif cat[0] in ("S", "P"):
                toks.append(_Tok("SYM", ch, i))
            else:
                raise MathSyntaxError(f"Karakter U+{ord(ch):04X} tidak didukung dalam ekspresi matematika.", i)
        i += 1
    toks.append(_Tok("EOF", "", n))
    return toks


def _unwrap(node: Node) -> Node:
    """Buang tanda kurung bulat terluar pada operand pecahan/skrip."""
    if isinstance(node, Delim) and node.open == "(" and node.close == ")":
        return node.inner
    return node


class _Parser:
    def __init__(self, toks: list[_Tok], limits: Limits) -> None:
        self.toks = toks
        self.i = 0
        self.limits = limits
        self.nodes = 0

    # --- util ---------------------------------------------------------------
    def peek(self) -> _Tok:
        return self.toks[self.i]

    def next(self) -> _Tok:
        t = self.toks[self.i]
        if t.kind != "EOF":
            self.i += 1
        return t

    def err(self, msg: str, tok: _Tok | None = None) -> MathSyntaxError:
        return MathSyntaxError(msg, (tok or self.peek()).pos)

    def count(self) -> None:
        self.nodes += 1
        if self.nodes > self.limits.max_math_nodes:
            raise MathSyntaxError(f"Ekspresi terlalu kompleks (lebih dari {self.limits.max_math_nodes} elemen).", self.peek().pos)

    def check_depth(self, depth: int) -> None:
        if depth > self.limits.max_math_depth:
            raise self.err(f"Kedalaman bersarang melebihi batas {self.limits.max_math_depth}.")

    # --- tata bahasa -----------------------------------------------------------
    def parse_all(self) -> Node:
        row = self.row(0, stop_comma=False)
        tok = self.peek()
        if tok.kind != "EOF":
            raise self.err(f"Tanda penutup {tok.value!r} tidak memiliki pembuka.", tok)
        if not row.items:
            raise MathSyntaxError("Ekspresi kosong.", 0)
        return row

    def row(self, depth: int, stop_comma: bool) -> Row:
        self.check_depth(depth)
        items: list[Node] = []
        while True:
            tok = self.peek()
            if tok.kind in ("EOF", "CLOSE"):
                break
            if stop_comma and tok.kind == "SYM" and tok.value == ",":
                break
            items.append(self.item(depth))
        self.count()
        return Row(tuple(items))

    def item(self, depth: int) -> Node:
        node = self.power(depth)
        while self.peek().kind == "SYM" and self.peek().value == "/":
            slash = self.next()
            if self.peek().kind in ("EOF", "CLOSE") or (self.peek().kind == "SYM" and self.peek().value in ",/"):
                raise self.err("Penyebut pecahan tidak ada setelah '/'.", slash)
            den = self.power(depth)
            self.count()
            node = Frac(_unwrap(node), _unwrap(den))
        return node

    def power(self, depth: int) -> Node:
        base = self.primary(depth)
        sub = sup = None
        for _ in range(2):
            tok = self.peek()
            if tok.kind == "SYM" and tok.value == "_" and sub is None:
                self.next()
                sub = self.script(depth)
            elif tok.kind == "SYM" and tok.value == "^" and sup is None:
                self.next()
                sup = self.script(depth)
            else:
                break
        tok = self.peek()
        if tok.kind == "SYM" and tok.value in "_^":
            raise self.err("Indeks atau pangkat ganda; gunakan tanda kurung, mis. x^(a^b).", tok)
        node: Node = base
        if sub is not None or sup is not None:
            self.count()
            node = Script(base, sub, sup)
        while self.peek().kind == "SYM" and self.peek().value == "!":
            self.next()
            self.count()
            node = Row((node, Sym("!")))
        return node

    def script(self, depth: int) -> Node:
        self.check_depth(depth + 1)
        sign: Sym | None = None
        tok = self.peek()
        if tok.kind == "SYM" and tok.value in ("+", "−"):
            sign = Sym(tok.value)
            self.next()
        tok = self.peek()
        if tok.kind in ("EOF", "CLOSE") or (tok.kind == "SYM" and tok.value in "^_/,"):
            raise self.err("Pangkat/indeks tidak memiliki nilai.", tok)
        atom = _unwrap(self.primary(depth + 1))
        if sign is not None:
            self.count()
            return Row((sign, atom))
        return atom

    def group(self, depth: int) -> Delim:
        open_tok = self.next()
        if open_tok.value == "{":
            raise self.err("Kurung kurawal '{ }' tidak digunakan sebagai pengelompok; pakai ( ).", open_tok)
        inner = self.row(depth + 1, stop_comma=False)
        close = self.peek()
        if close.kind != "CLOSE":
            raise self.err(f"Tanda kurung {open_tok.value!r} tidak ditutup.", open_tok)
        if close.value != OPEN[open_tok.value]:
            raise self.err(f"Kurung {open_tok.value!r} tidak cocok dengan {close.value!r}.", close)
        self.next()
        self.count()
        return Delim(open_tok.value, close.value, inner)

    def call_args(self, name: str, depth: int, expected: int, allow_empty: tuple[int, ...] = ()) -> list[Row]:
        tok = self.peek()
        if tok.kind != "OPEN" or tok.value != "(":
            raise self.err(f"{name} membutuhkan argumen dalam tanda kurung, mis. {name}(...).", tok)
        self.next()
        args: list[Row] = []
        while True:
            args.append(self.row(depth + 1, stop_comma=True))
            tok = self.peek()
            if tok.kind == "SYM" and tok.value == ",":
                self.next()
                continue
            if tok.kind == "CLOSE" and tok.value == ")":
                self.next()
                break
            raise self.err(f"Tanda kurung pada {name}(...) tidak ditutup.", tok)
        if len(args) != expected:
            raise self.err(f"{name}(...) membutuhkan tepat {expected} argumen, ditemukan {len(args)}.")
        for idx, a in enumerate(args):
            if not a.items and idx not in allow_empty:
                raise self.err(f"Argumen ke-{idx + 1} pada {name}(...) kosong.")
        return args

    def primary(self, depth: int) -> Node:
        self.check_depth(depth)
        tok = self.peek()
        k = tok.kind
        if k == "NUM":
            self.next(); self.count()
            return Num(tok.value)
        if k == "VAR":
            self.next(); self.count()
            return Var(tok.value)
        if k == "STR":
            self.next(); self.count()
            return Text(tok.value)
        if k == "OPEN":
            return self.group(depth)
        if k == "CLOSE":
            raise self.err(f"Tanda penutup {tok.value!r} tidak memiliki pembuka.", tok)
        if k == "EOF":
            raise self.err("Ekspresi berakhir tiba-tiba.", tok)
        if k == "SYM":
            if tok.value in "^_/":
                raise self.err(f"Operator {tok.value!r} membutuhkan operan di sebelah kirinya.", tok)
            self.next(); self.count()
            if tok.value == "√":
                arg = _unwrap(self.power(depth + 1))
                return Radical(arg)
            return Sym(tok.value)
        # WORD
        self.next()
        w = tok.value
        self.count()
        if w in GREEK_LOWER:
            return Var(GREEK_LOWER[w])
        if w in GREEK_UPPER:
            return Var(GREEK_UPPER[w], upright=True)
        if w in WORD_SYMBOLS:
            return Sym(WORD_SYMBOLS[w])
        if w == "text":
            args = self.call_args(w, depth, 1)
            inner = args[0].items
            if len(inner) != 1 or not isinstance(inner[0], Text):
                raise self.err("text(...) membutuhkan satu teks bertanda kutip tunggal, mis. text('kecepatan').", tok)
            return inner[0]
        if w == "sqrt":
            return Radical(self.call_args(w, depth, 1)[0])
        if w == "root":
            a = self.call_args(w, depth, 2)
            return Radical(a[1], a[0])
        if w == "frac":
            a = self.call_args(w, depth, 2)
            return Frac(a[0], a[1])
        if w == "abs":
            return Delim("|", "|", self.call_args(w, depth, 1)[0])
        if w == "norm":
            return Delim("‖", "‖", self.call_args(w, depth, 1)[0])
        if w in NARY_CHARS:
            a = self.call_args(w, depth, 3, allow_empty=(0, 1))
            return NAry(NARY_CHARS[w], a[0] if a[0].items else None, a[1] if a[1].items else None, a[2])
        if w == "lim":
            a = self.call_args(w, depth, 2)
            return Func("lim", arg=a[1], under=a[0])
        return self.function(w, depth)

    def function(self, name: str, depth: int) -> Node:
        sub = sup = None
        for _ in range(2):
            tok = self.peek()
            if tok.kind == "SYM" and tok.value == "_" and sub is None:
                self.next(); sub = self.script(depth)
            elif tok.kind == "SYM" and tok.value == "^" and sup is None:
                self.next(); sup = self.script(depth)
        tok = self.peek()
        arg: Node | None = None
        starts_arg = tok.kind in ("NUM", "VAR", "STR", "OPEN") or (tok.kind == "WORD") or (
            tok.kind == "SYM" and tok.value == "√"
        )
        if starts_arg:
            arg = self.power(depth + 1)
        self.count()
        return Func(name, arg=arg, sub=sub, sup=sup)


def parse_math(source: str, limits: Limits | None = None) -> ParsedMath:
    """Parse ekspresi DSX-Math. Melempar MathSyntaxError jika tidak valid."""
    limits = limits or Limits()
    if not isinstance(source, str):
        raise MathSyntaxError("Ekspresi harus berupa string.", 0)
    text = unicodedata.normalize("NFC", source)
    if len(text) > limits.max_math_chars:
        raise MathSyntaxError(f"Ekspresi melebihi {limits.max_math_chars} karakter.", 0)
    if not text.strip():
        raise MathSyntaxError("Ekspresi kosong.", 0)
    parser = _Parser(_tokenize(text), limits)
    tree = parser.parse_all()
    return ParsedMath(text, tree, parser.nodes)
