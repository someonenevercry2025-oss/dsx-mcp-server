#!/usr/bin/env python3
"""DSX MCP Server (remote-ready) — expose DocScript AI tools to Claude / MCP clients.

Transport: Streamable HTTP (recommended for remote) or stdio (local).
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

# Make vendored dsx importable
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "src"))

from mcp.server.fastmcp import FastMCP

import dsx
from dsx import (
    GenerationResult,
    Limits,
    check_document,
    generate_document,
)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="dsx",
    instructions=(
        "DSX (DocScript AI) is a declarative language for structured documents. "
        "Use these tools to validate DSX source and compile it to DOCX (or PDF). "
        "Prefer check_dsx before generate_dsx when the document is complex. "
        "Return base64-encoded document bytes so the client can save the file."
    ),
)


def _diag_to_dict(d: Any) -> dict[str, Any]:
    loc = None
    if getattr(d, "location", None) is not None:
        loc = {
            "file": getattr(d.location, "file", None),
            "line": getattr(d.location, "line", None),
            "column": getattr(d.location, "column", None),
        }
    return {
        "severity": str(getattr(d.severity, "name", d.severity)),
        "code": d.code,
        "message": d.message,
        "location": loc,
    }


def _result_payload(r: GenerationResult, include_bytes: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": r.ok,
        "status": r.status,
        "diagnostics": [_diag_to_dict(d) for d in (r.diagnostics or [])],
        "warnings": [_diag_to_dict(d) for d in (r.warnings or [])],
        "render_summary": r.render_summary or {},
        "referenced_files": r.referenced_files or [],
        "dsx_version": dsx.__version__,
        "language_version": dsx.LANGUAGE_VERSION,
    }
    if include_bytes and r.output is not None:
        out["output_base64"] = base64.b64encode(r.output).decode("ascii")
        out["output_size_bytes"] = len(r.output)
        out["output_format_hint"] = "docx"  # default; client knows from request
    return out


def _parse_project_files(project_files_json: str | None) -> dict[str, bytes] | None:
    if not project_files_json or not project_files_json.strip():
        return None
    raw = json.loads(project_files_json)
    if not isinstance(raw, dict):
        raise ValueError("project_files must be a JSON object of path -> content")
    result: dict[str, bytes] = {}
    for path, content in raw.items():
        if isinstance(content, str):
            # Allow plain text or base64 (prefix b64:)
            if content.startswith("b64:"):
                result[path] = base64.b64decode(content[4:])
            else:
                result[path] = content.encode("utf-8")
        elif isinstance(content, (bytes, bytearray)):
            result[path] = bytes(content)
        else:
            raise ValueError(f"Unsupported content type for {path}")
    return result


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def check_dsx(
    source: str,
    source_name: str = "document.dsx",
    project_files: str | None = None,
) -> str:
    """Validate DSX source without rendering.

    Args:
        source: Full DSX document text.
        source_name: Logical filename used in diagnostics (default document.dsx).
        project_files: Optional JSON object mapping relative paths to file content
            (UTF-8 text or "b64:..." for binary). Used for FILE/IMAGE/CSV references.

    Returns:
        JSON with ok, diagnostics, warnings, referenced_files.
    """
    try:
        files = _parse_project_files(project_files)
        r = check_document(
            source,
            project_files=files,
            source_name=source_name,
        )
        return json.dumps(_result_payload(r, include_bytes=False), ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {
                "ok": False,
                "status": "failed",
                "diagnostics": [{"severity": "ERROR", "code": "INTERNAL_ERROR", "message": str(exc)}],
                "warnings": [],
            },
            ensure_ascii=False,
            indent=2,
        )


@mcp.tool()
def generate_dsx(
    source: str,
    output_format: str = "docx",
    source_name: str = "document.dsx",
    project_files: str | None = None,
) -> str:
    """Compile DSX source into a document (DOCX or PDF).

    Args:
        source: Full DSX document text.
        output_format: "docx" (always available) or "pdf" (needs LibreOffice on the host).
        source_name: Logical filename for diagnostics.
        project_files: Optional JSON object of relative path -> content
            (text or "b64:..." for binary assets).

    Returns:
        JSON with ok, diagnostics, warnings, and output_base64 (document bytes) on success.
        Decode the base64 and write a .docx / .pdf file on the client side.
    """
    fmt = (output_format or "docx").lower().strip()
    if fmt not in ("docx", "pdf"):
        return json.dumps(
            {
                "ok": False,
                "status": "failed",
                "diagnostics": [
                    {
                        "severity": "ERROR",
                        "code": "UNSUPPORTED_FORMAT",
                        "message": f"Format {fmt!r} not supported. Use docx or pdf.",
                    }
                ],
                "warnings": [],
            },
            ensure_ascii=False,
            indent=2,
        )
    try:
        files = _parse_project_files(project_files)
        r = generate_document(
            source,
            project_files=files,
            output_format=fmt,
            source_name=source_name,
        )
        payload = _result_payload(r, include_bytes=True)
        payload["output_format_hint"] = fmt
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {
                "ok": False,
                "status": "failed",
                "diagnostics": [{"severity": "ERROR", "code": "INTERNAL_ERROR", "message": str(exc)}],
                "warnings": [],
            },
            ensure_ascii=False,
            indent=2,
        )


@mcp.tool()
def dsx_info() -> str:
    """Return DSX version, language version, and a short capability summary."""
    return json.dumps(
        {
            "package_version": dsx.__version__,
            "language_version": dsx.LANGUAGE_VERSION,
            "supported_formats": ["docx", "pdf"],
            "pdf_note": "PDF requires LibreOffice (soffice) on the host; DOCX always works.",
            "main_constructs": [
                "DOC", "PAGE", "STYLE", "STYLEDEF", "HEADER", "FOOTER", "PAGENUM",
                "TEXT", "P", "H1-H9", "TEXTBLOCK", "FIGURE", "TABLE", "PAGEBREAK",
                "CALLOUT", "LIST", "BULLET", "MATH", "IMATH", "TOC",
                "FILE", "IMAGE", "CSV", "BOLD", "ITALIC", "UNDERLINE", "LINK", "FOOTNOTE",
            ],
            "docs": "See language-spec and user-guide resources or the skill-dsx package.",
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def dsx_language_cheatsheet() -> str:
    """Return a compact DSX language cheat sheet for generating correct source."""
    return """# DSX Language Cheat Sheet (v2.4 / package 0.4)

## Skeleton
```
DOC(
  title="Judul",
  author="Nama",
  template="default",   # or academic-paper, project-report
  PAGE(size="A4", margin="2.5cm"),
  STYLE(...),           # optional overrides
  # content blocks...
)
```

## Content blocks
- H1("Judul") … H9(...)
- P("teks") atau P(["run ", BOLD("tebal"), " ", ITALIC("miring")])
- TEXTBLOCK(FILE("content/bab1.txt"))
- LIST(["item1", "item2", ["sub-a", "sub-b"]], ordered=true)
- BULLET([...])
- TABLE(headers=["A","B"], rows=[["1","2"], ...]) atau TABLE(data=CSV("data.csv"))
- FIGURE(IMAGE("assets/img.png"), caption="...", alt="...", width="12cm")
- CALLOUT("isi", type="info|warning|tip|note", title="Opsional")
- MATH("a^2 + b^2 = c^2", align="center")
- PAGEBREAK()
- TOC()

## Inline
- BOLD / ITALIC / UNDERLINE / LINK("url", "label") / FOOTNOTE("teks")
- IMATH("x_i") di dalam P([...])

## Values
- FILE("path/relatif.txt")  — multi-paragraf
- IMAGE("path.png") / CSV("data.csv")
- Semua path relatif ke root proyek (sandbox)

## Tips
1. Selalu validasi dulu dengan check_dsx.
2. Asset binary kirim lewat project_files sebagai "b64:<base64>".
3. Output generate_dsx adalah base64 — decode lalu simpan sebagai .docx.
"""


# ---------------------------------------------------------------------------
# Resources (optional docs for the model)
# ---------------------------------------------------------------------------


@mcp.resource("dsx://version")
def resource_version() -> str:
    return f"DSX {dsx.__version__} (language {dsx.LANGUAGE_VERSION})"


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Default: streamable HTTP for remote hosting.
    # Override with MCP_TRANSPORT=stdio for local Claude Desktop / Claude Code stdio.
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http").lower()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("MCP_PORT", "8000")))

    if transport in ("stdio", "std"):
        mcp.run(transport="stdio")
    else:
        # FastMCP streamable HTTP
        mcp.run(transport="streamable-http", host=host, port=port)
