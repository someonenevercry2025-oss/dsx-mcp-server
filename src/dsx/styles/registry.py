"""Registri style: pewarisan, validasi, dan resolusi sebelum rendering.

Urutan resolusi (Blueprint VII.7):
  default engine -> template -> STYLE global -> pewarisan STYLEDEF -> style komponen -> override lokal.
Registri ini menangani tiga lapisan pertama dan pewarisan; pemilihan style
komponen dan override lokal dilakukan oleh IR builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..diagnostics import DiagnosticBag, Location
from ..schema import VISUAL_KEYS
from ..templates.registry import Template
from ..validator import BoundCall, hint_for
from .defaults import BUILTIN_STYLES, ENGINE_BASE, ROLE_DEFAULT_STYLE


@dataclass(frozen=True)
class ResolvedStyle:
    name: str
    role: str | None
    level: int | None
    props: dict[str, Any]
    parent: str | None
    builtin: bool
    user_defined: bool
    chain: tuple[str, ...]


@dataclass
class _Def:
    name: str
    parent: str | None
    role: str | None
    level: int | None
    props: dict[str, Any]
    loc: Location | None
    builtin: bool
    user: bool


class StyleRegistry:
    def __init__(self, template: Template, global_props: dict[str, Any], diag: DiagnosticBag) -> None:
        self._diag = diag
        self._base: dict[str, Any] = {**ENGINE_BASE, **template.normal, **global_props}
        self._defs: dict[str, _Def] = {}
        self._user_locs: dict[str, Location] = {}
        self._fold: dict[str, str] = {}
        self._resolved: dict[str, ResolvedStyle | None] = {}
        for name, role, level, parent, props in BUILTIN_STYLES:
            merged = dict(props) if name == "normal" else {**props, **template.styles.get(name, {})}
            self._defs[name] = _Def(name, parent, role, level, merged, None, True, False)
            self._fold[name.casefold()] = name

    # ---------------------------------------------------------------- define
    def define(self, b: BoundCall) -> None:
        name: str = b.args["name"]
        loc = b.loc
        if name in self._user_locs:
            self._diag.error(
                "DUPLICATE_STYLE",
                f"Style {name!r} sudah didefinisikan.",
                loc,
                first_defined=str(self._user_locs[name]),
            )
            return
        existing = self._fold.get(name.casefold())
        if existing is not None and existing != name:
            self._diag.error(
                "DUPLICATE_STYLE",
                f"Nama style {name!r} bentrok dengan {existing!r} (nama style tidak membedakan huruf besar/kecil karena batasan Word).",
                loc,
            )
            return
        extends = b.get("extends")
        urole = b.get("role")
        ulevel = b.get("level")
        props = {k: b.args[k] for k in VISUAL_KEYS if k in b.args}
        if name == "normal" and extends is not None:
            self._diag.error("NORMAL_CANNOT_EXTEND", "Style 'normal' adalah akar dan tidak dapat memakai extends.", b.loc_of("extends"))
            extends = None
        self._user_locs[name] = loc
        self._fold[name.casefold()] = name
        builtin = self._defs.get(name)
        if builtin is not None and builtin.builtin:
            if urole is not None and urole != builtin.role:
                self._diag.error(
                    "STYLE_ROLE_CONFLICT",
                    f"Style bawaan {name!r} memiliki role {builtin.role!r} yang tidak dapat diubah.",
                    b.loc_of("role"),
                    found=f"role={urole}",
                )
                urole = None
            if ulevel is not None and ulevel != builtin.level:
                self._diag.error(
                    "STYLE_ROLE_CONFLICT",
                    f"Style bawaan {name!r} memiliki level {builtin.level!r} yang tidak dapat diubah.",
                    b.loc_of("level"),
                    found=f"level={ulevel}",
                )
            merged = {**builtin.props, **props} if extends is None else props
            parent = None if name == "normal" else (builtin.parent if extends is None else extends)
            self._defs[name] = _Def(name, parent, builtin.role, builtin.level, merged, loc, True, True)
            return
        if ulevel is not None and urole is not None and urole != "heading":
            self._diag.error("LEVEL_WITHOUT_HEADING", "Argumen level hanya berlaku untuk role 'heading'.", b.loc_of("level"))
            ulevel = None
        self._defs[name] = _Def(name, extends or "normal", urole, ulevel, props, loc, False, True)

    # -------------------------------------------------------------- finalize
    def finalize(self) -> None:
        for name in list(self._defs):
            self._resolve(name, ())

    def _resolve(self, name: str, stack: tuple[str, ...]) -> ResolvedStyle | None:
        if name in self._resolved:
            return self._resolved[name]
        d = self._defs[name]
        if name in stack:
            chain = stack[stack.index(name) :] + (name,)
            self._diag.error(
                "STYLE_INHERITANCE_CYCLE",
                "Pewarisan style membentuk siklus.",
                d.loc,
                chain=" -> ".join(chain),
            )
            return None
        if d.parent is None:
            props = {**self._base, **d.props}
            result = ResolvedStyle(name, d.role, d.level, props, None, d.builtin, d.user, (name,))
            self._resolved[name] = result
            return result
        if d.parent not in self._defs:
            self._diag.error(
                "STYLE_NOT_FOUND",
                f"Style induk {d.parent!r} (extends) tidak ditemukan.",
                d.loc,
                hint=hint_for(d.parent, self._defs),
            )
            self._resolved[name] = None
            return None
        parent = self._resolve(d.parent, stack + (name,))
        if parent is None:
            self._resolved[name] = None
            return None
        role = d.role if d.role is not None else parent.role
        if d.level is not None:
            level: int | None = d.level
            if role != "heading":
                self._diag.error("LEVEL_WITHOUT_HEADING", f"Style {name!r} memiliki level tetapi role bukan 'heading'.", d.loc)
                level = None
        elif role == "heading" and parent.role == "heading":
            level = parent.level
        else:
            level = None
        props = {**parent.props, **d.props}
        result = ResolvedStyle(name, role, level, props, d.parent, d.builtin, d.user, parent.chain + (name,))
        self._resolved[name] = result
        return result

    # ----------------------------------------------------------------- query
    def exists(self, name: str) -> bool:
        return name in self._defs

    def names(self) -> list[str]:
        return list(self._defs)

    def get(self, name: str) -> ResolvedStyle | None:
        if name not in self._resolved:
            self._resolve(name, ()) if name in self._defs else None
        return self._resolved.get(name)

    def style_for_role(self, role: str) -> ResolvedStyle | None:
        return self.get(ROLE_DEFAULT_STYLE[role])

    def heading_style(self, level: int) -> ResolvedStyle | None:
        return self.get(f"heading-{level}")

    def user_defined_names(self) -> list[str]:
        return [n for n, d in self._defs.items() if d.user]
