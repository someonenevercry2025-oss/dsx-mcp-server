"""Renderer PDF: DOCX → PDF lewat LibreOffice (soffice) bila tersedia."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..ir.nodes import DocumentIR
from ..limits import Deadline
from .base import Renderer
from .docx import DocxRenderer


class PdfRenderError(RuntimeError):
    pass


def _find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    # common install locations
    for candidate in (
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/usr/lib/libreoffice/program/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class PdfRenderer(Renderer):
    format = "pdf"

    def render(self, ir: DocumentIR, deadline: Deadline | None = None) -> bytes:
        soffice = _find_soffice()
        if soffice is None:
            raise PdfRenderError(
                "LibreOffice (soffice) tidak ditemukan. Pasang LibreOffice untuk ekspor PDF, "
                "atau bangun DOCX lalu konversi secara manual."
            )
        docx_bytes = DocxRenderer().render(ir, deadline)
        if deadline is not None:
            deadline.check()
        with tempfile.TemporaryDirectory(prefix="dsx-pdf-") as tmp:
            tmp_path = Path(tmp)
            docx_path = tmp_path / "document.docx"
            docx_path.write_bytes(docx_bytes)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            cmd = [
                soffice,
                "--headless",
                "--nologo",
                "--nolockcheck",
                "--nodefault",
                "--norestore",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(out_dir),
                str(docx_path),
            ]
            env = os.environ.copy()
            env.setdefault("HOME", tmp)
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=120,
                    env=env,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise PdfRenderError("Konversi PDF melebihi batas waktu (120s).") from exc
            except OSError as exc:
                raise PdfRenderError(f"Gagal menjalankan LibreOffice: {exc}") from exc
            pdf_path = out_dir / "document.pdf"
            if not pdf_path.is_file():
                err = (proc.stderr or b"").decode("utf-8", "replace")[:500]
                raise PdfRenderError(
                    f"Konversi PDF gagal (kode {proc.returncode}). {err or 'Berkas PDF tidak dihasilkan.'}"
                )
            if deadline is not None:
                deadline.check()
            return pdf_path.read_bytes()
