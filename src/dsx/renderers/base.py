"""Antarmuka renderer. Renderer hanya menerima Document IR yang sudah divalidasi."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..ir.nodes import DocumentIR
from ..limits import Deadline


class Renderer(ABC):
    format: str = ""

    @abstractmethod
    def render(self, ir: DocumentIR, deadline: Deadline | None = None) -> bytes:
        """Hasilkan dokumen sebagai bytes."""


def get_renderer(fmt: str) -> Renderer | None:
    if fmt == "docx":
        from .docx import DocxRenderer

        return DocxRenderer()
    if fmt == "pdf":
        from .pdf import PdfRenderer

        return PdfRenderer()
    return None


SUPPORTED_FORMATS = ("docx", "pdf")
