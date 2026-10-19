"""Antarmuka baris perintah: python -m dsx build|check PATH.

Kode keluar: 0 berhasil, 1 dokumen/diagnostik gagal, 2 kesalahan penggunaan.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import LANGUAGE_VERSION, __version__
from .api.service import GenerationResult, generate_from_directory
from .renderers.base import SUPPORTED_FORMATS


def _resolve_target(path: str) -> tuple[Path, str] | None:
    target = Path(path)
    if target.is_dir():
        return target, "document.dsx"
    if target.suffix.lower() == ".dsx":
        return (target.parent if str(target.parent) else Path(".")), target.name
    return None


def _report(result: GenerationResult, as_json: bool) -> None:
    if as_json:
        payload = {
            "status": result.status,
            "output_file": result.output_file,
            "diagnostics": [d.to_dict() for d in result.diagnostics],
            "warnings": [d.to_dict() for d in result.warnings],
            "render_summary": result.render_summary,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for item in result.diagnostics + result.warnings:
        print(item.format(), file=sys.stderr)
        print(file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dsx", description="DocScript AI (DSX) engine")
    parser.add_argument("--version", action="version", version=f"dsx {__version__} (bahasa DSX {LANGUAGE_VERSION})")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "check"):
        p = sub.add_parser(name, help="bangun dokumen" if name == "build" else "validasi tanpa rendering")
        p.add_argument("path", help="direktori proyek (berisi document.dsx) atau file .dsx")
        p.add_argument("--json", action="store_true", help="keluaran diagnostik dalam JSON")
        if name == "build":
            p.add_argument("-o", "--output", help="berkas keluaran (default: <nama dsx>.docx di folder proyek)")
            p.add_argument("--format", default="docx", choices=SUPPORTED_FORMATS, help="format keluaran: docx atau pdf (pdf membutuhkan LibreOffice)")
            p.add_argument("--no-overwrite", action="store_true", help="jangan timpa berkas keluaran yang sudah ada")
    args = parser.parse_args(argv)
    resolved = _resolve_target(args.path)
    if resolved is None:
        print(f"ERROR: argumen harus berupa direktori proyek atau file .dsx: {args.path}", file=sys.stderr)
        return 2
    project_dir, dsx_name = resolved
    try:
        if args.command == "check":
            result = generate_from_directory(project_dir, None, dsx_name=dsx_name, check_only=True)
        else:
            output = args.output or str(project_dir / (Path(dsx_name).stem + "." + args.format))
            result = generate_from_directory(
                project_dir, output, args.format, dsx_name=dsx_name, overwrite=not args.no_overwrite
            )
    except KeyboardInterrupt:
        print("Dibatalkan.", file=sys.stderr)
        return 130
    _report(result, args.json)
    if not result.ok:
        return 1
    if not args.json:
        print(f"OK: {result.output_file}" if args.command == "build" else "OK: dokumen valid")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
