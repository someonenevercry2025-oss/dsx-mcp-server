"""Akses file proyek yang aman.

Semua referensi eksternal harus berada di dalam direktori proyek (Blueprint X.1).
Pemeriksaan dilakukan setelah normalisasi path dan resolusi symbolic link.
"""

from __future__ import annotations

import csv
import io
import os
import posixpath
import re
import stat
from pathlib import Path
from typing import Mapping

from .limits import Limits
from .textutil import describe_char, find_illegal_xml_char, normalize_newlines


class SourceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_DRIVE = re.compile(r"^[A-Za-z]:")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def normalize_relpath(path: object) -> str:
    """Normalisasi path relatif bergaya POSIX, atau tolak jika tidak aman."""
    if not isinstance(path, str) or not path.strip():
        raise SourceError("INVALID_PATH", "Path file harus berupa string yang tidak kosong.")
    if len(path) > 1024:
        raise SourceError("INVALID_PATH", "Path file terlalu panjang.")
    if _CONTROL.search(path):
        raise SourceError("INVALID_PATH", "Path file mengandung karakter kontrol.")
    if "\\" in path:
        raise SourceError("INVALID_PATH", "Gunakan '/' sebagai pemisah path, bukan '\\'.")
    if path.startswith("/") or _DRIVE.match(path):
        raise SourceError("PATH_OUTSIDE_PROJECT", "Path absolut tidak diizinkan; gunakan path relatif terhadap proyek.")
    if ":" in path:
        raise SourceError("INVALID_PATH", "Karakter ':' tidak diizinkan dalam path.")
    normalized = posixpath.normpath(path)
    if normalized == ".":
        raise SourceError("INVALID_PATH", "Path tidak menunjuk ke sebuah file.")
    if normalized == ".." or normalized.startswith("../"):
        raise SourceError("PATH_OUTSIDE_PROJECT", "Path mengarah ke luar direktori proyek.")
    for part in normalized.split("/"):
        if len(part) > 255:
            raise SourceError("INVALID_PATH", "Nama file atau folder terlalu panjang.")
    return normalized


class Source:
    """Antarmuka sumber file proyek."""

    def read(self, path: str, max_bytes: int) -> bytes:  # pragma: no cover - antarmuka
        raise NotImplementedError


class DirectorySource(Source):
    def __init__(self, root: str | os.PathLike[str]) -> None:
        resolved = Path(root).resolve(strict=True)
        if not resolved.is_dir():
            raise NotADirectoryError(f"Bukan direktori: {root}")
        self.root = resolved

    def read(self, path: str, max_bytes: int) -> bytes:
        rel = normalize_relpath(path)
        candidate = self.root.joinpath(*rel.split("/"))
        try:
            real = candidate.resolve(strict=True)
        except (FileNotFoundError, NotADirectoryError):
            raise SourceError("FILE_NOT_FOUND", "File tidak ditemukan.") from None
        except (OSError, RuntimeError):
            raise SourceError("FILE_UNREADABLE", "File tidak dapat dibaca (mungkin symbolic link yang rusak atau berputar).") from None
        if not real.is_relative_to(self.root):
            raise SourceError("PATH_OUTSIDE_PROJECT", "Path mengarah ke luar direktori proyek.")
        flags = os.O_RDONLY
        flags |= getattr(os, "O_NONBLOCK", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(real, flags)
        except OSError:
            raise SourceError("FILE_UNREADABLE", "File tidak dapat dibuka.") from None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise SourceError("FILE_UNREADABLE", "Path bukan file biasa.")
            if info.st_size > max_bytes:
                raise SourceError("FILE_TOO_LARGE", f"Ukuran file melebihi batas {max_bytes} byte.")
            with os.fdopen(fd, "rb", closefd=True) as handle:
                fd = -1
                data = handle.read(max_bytes + 1)
        except SourceError:
            if fd != -1:
                os.close(fd)
            raise
        except OSError:
            if fd != -1:
                os.close(fd)
            raise SourceError("FILE_UNREADABLE", "File tidak dapat dibaca.") from None
        if len(data) > max_bytes:
            raise SourceError("FILE_TOO_LARGE", f"Ukuran file melebihi batas {max_bytes} byte.")
        return data


class MemorySource(Source):
    def __init__(self, files: Mapping[str, bytes | str] | None = None) -> None:
        self._files: dict[str, bytes] = {}
        if files is None:
            files = {}
        if not isinstance(files, Mapping):
            raise ValueError(
                f"project_files harus berupa dict (nama file -> isi bytes/str) atau None, ditemukan {type(files).__name__}."
            )
        for key, value in files.items():
            try:
                rel = normalize_relpath(key)
            except SourceError as exc:
                raise ValueError(f"Nama file proyek tidak valid {key!r}: {exc.message}") from None
            if rel in self._files:
                raise ValueError(f"Nama file proyek duplikat setelah normalisasi: {rel!r}")
            if isinstance(value, str):
                value = value.encode("utf-8")
            if not isinstance(value, (bytes, bytearray)):
                raise ValueError(f"Isi file {key!r} harus berupa bytes atau str.")
            self._files[rel] = bytes(value)

    def read(self, path: str, max_bytes: int) -> bytes:
        rel = normalize_relpath(path)
        data = self._files.get(rel)
        if data is None:
            raise SourceError("FILE_NOT_FOUND", "File tidak ditemukan.")
        if len(data) > max_bytes:
            raise SourceError("FILE_TOO_LARGE", f"Ukuran file melebihi batas {max_bytes} byte.")
        return data


class ImageInfo:
    __slots__ = ("px_width", "px_height", "dpi_x", "dpi_y", "content_type")

    def __init__(self, px_width: int, px_height: int, dpi_x: float, dpi_y: float, content_type: str) -> None:
        self.px_width = px_width
        self.px_height = px_height
        self.dpi_x = dpi_x
        self.dpi_y = dpi_y
        self.content_type = content_type


class ContentStore:
    """Cache konten referensi dengan penegakan batas sumber daya."""

    def __init__(self, source: Source, limits: Limits) -> None:
        self._source = source
        self._limits = limits
        self._bytes: dict[str, bytes] = {}
        self._text: dict[str, str] = {}
        self._csv: dict[tuple[str, str], list[list[str]]] = {}
        self._images: dict[str, ImageInfo] = {}
        self._total = 0

    def _max_for(self, kind: str) -> int:
        if kind == "image":
            return self._limits.max_image_bytes
        if kind == "csv":
            return self._limits.max_csv_bytes
        return self._limits.max_content_bytes

    def load(self, rel: str, kind: str) -> bytes:
        limit = self._max_for(kind)
        cached = self._bytes.get(rel)
        if cached is not None:
            if len(cached) > limit:
                raise SourceError("FILE_TOO_LARGE", f"Ukuran file melebihi batas {limit} byte.")
            return cached
        if len(self._bytes) >= self._limits.max_referenced_files:
            raise SourceError("RESOURCE_LIMIT", f"Jumlah file referensi melebihi batas {self._limits.max_referenced_files}.")
        data = self._source.read(rel, limit)
        if self._total + len(data) > self._limits.max_total_bytes:
            raise SourceError("RESOURCE_LIMIT", "Total ukuran file referensi melebihi batas.")
        self._total += len(data)
        self._bytes[rel] = data
        return data

    def text(self, rel: str) -> str:
        cached = self._text.get(rel)
        if cached is not None:
            return cached
        data = self.load(rel, "text")
        try:
            decoded = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SourceError("INVALID_ENCODING", f"File bukan UTF-8 yang valid (byte ke-{exc.start}).") from None
        decoded = normalize_newlines(decoded)
        bad = find_illegal_xml_char(decoded)
        if bad is not None:
            raise SourceError(
                "INVALID_CONTENT",
                f"File mengandung karakter yang tidak valid ({describe_char(decoded[bad])}) pada posisi {bad}.",
            )
        self._text[rel] = decoded
        return decoded

    def csv_rows(self, rel: str, delimiter: str) -> list[list[str]]:
        key = (rel, delimiter)
        cached = self._csv.get(key)
        if cached is not None:
            return cached
        self.load(rel, "csv")
        text = self.text(rel)
        rows: list[list[str]] = []
        try:
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
            for row in reader:
                if not row:
                    continue
                if len(rows) >= self._limits.max_table_rows + 1:
                    raise SourceError("RESOURCE_LIMIT", f"Jumlah baris CSV melebihi batas {self._limits.max_table_rows}.")
                rows.append(row)
        except csv.Error as exc:
            raise SourceError("INVALID_CSV", f"CSV tidak valid: {exc}") from None
        if rows:
            width = len(rows[0])
            if width > self._limits.max_table_columns:
                raise SourceError("RESOURCE_LIMIT", f"Jumlah kolom CSV melebihi batas {self._limits.max_table_columns}.")
            for number, row in enumerate(rows, start=1):
                if len(row) != width:
                    raise SourceError(
                        "INVALID_CSV",
                        f"Baris CSV ke-{number} memiliki {len(row)} kolom, diharapkan {width}.",
                    )
                for cell in row:
                    if len(cell) > self._limits.max_cell_chars:
                        raise SourceError("RESOURCE_LIMIT", f"Sel CSV pada baris {number} melebihi {self._limits.max_cell_chars} karakter.")
        self._csv[key] = rows
        return rows

    def image(self, rel: str) -> ImageInfo:
        cached = self._images.get(rel)
        if cached is not None:
            return cached
        data = self.load(rel, "image")
        try:
            from docx.image.image import Image

            image = Image.from_blob(data)
            width, height = int(image.px_width), int(image.px_height)
            dpi_x, dpi_y = float(image.horz_dpi), float(image.vert_dpi)
            content_type = str(image.content_type)
        except Exception:  # parser pihak ketiga dapat melempar berbagai jenis kesalahan
            raise SourceError("INVALID_IMAGE", "File bukan gambar yang valid (PNG, JPEG, GIF, atau BMP).") from None
        if width <= 0 or height <= 0:
            raise SourceError("INVALID_IMAGE", "Dimensi gambar tidak valid.")
        if width * height > self._limits.max_image_pixels:
            raise SourceError("RESOURCE_LIMIT", f"Dimensi gambar melebihi batas {self._limits.max_image_pixels} piksel.")
        if not (dpi_x > 0):
            dpi_x = 72.0
        if not (dpi_y > 0):
            dpi_y = 72.0
        info = ImageInfo(width, height, dpi_x, dpi_y, content_type)
        self._images[rel] = info
        return info

    def bytes_of(self, rel: str) -> bytes:
        return self._bytes[rel]

    def referenced(self) -> list[str]:
        """Path relatif semua file yang berhasil dirujuk/dibaca selama kompilasi."""
        return sorted(self._bytes)
