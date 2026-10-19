---
name: skill-dsx
description: Compile structured documents with DSX (DocScript AI). Use when the user asks to create, validate, or export professional Word/DOCX or PDF documents from a declarative DSX source, academic papers, reports, or multi-section structured content. Triggers include DSX, DocScript, generate docx, compile document, document.dsx, bahasa dokumen deklaratif.
---

# DSX Document Skill

DSX (DocScript AI) is a declarative language for building structured DOCX/PDF documents. Prefer the MCP tools `check_dsx` and `generate_dsx` when available.

## When to use

- User wants a Word (.docx) or PDF document with headings, tables, math, figures, lists, headers/footers.
- User provides or asks you to write a `.dsx` source file.
- Need reliable native Word equations (OMML), callouts, numbered lists, or project-style layouts.

## Workflow

1. **Draft** a complete DSX document (see cheat sheet below).
2. Call **`check_dsx`** with the source. Fix any diagnostics.
3. Call **`generate_dsx`** with `output_format="docx"` (preferred). PDF needs LibreOffice on the server.
4. Decode the returned `output_base64` and save as a `.docx` file for the user.
5. Optional assets (images, CSV, text includes): pass `project_files` as a JSON string mapping relative paths to content. Binary files use the prefix `b64:` + base64.

## Minimal example

```dsx
DOC(
  title="Laporan Singkat",
  author="Claude",
  PAGE(size="A4", margin="2.5cm"),
  H1("Pendahuluan"),
  P("Ini adalah paragraf pembuka."),
  H1("Data"),
  TABLE(
    headers=["Item", "Nilai"],
    rows=[["A", "10"], ["B", "20"]]
  ),
  H1("Persamaan"),
  MATH("E = mc^2", align="center"),
)
```

## Project layout (when using FILE / IMAGE / CSV)

```
project/
  document.dsx
  content/
    bab1.txt
  assets/
    diagram.png
  data/
    status.csv
```

Reference them as `FILE("content/bab1.txt")`, `IMAGE("assets/diagram.png")`, `CSV("data/status.csv")`.

## Language essentials

| Construct | Purpose |
|-----------|---------|
| `DOC(...)` | Root document |
| `PAGE(size, margin, ...)` | Page setup |
| `H1`…`H9` | Headings |
| `P(...)` | Paragraph (string or list of rich runs) |
| `LIST` / `BULLET` | Ordered / unordered lists (nestable) |
| `TABLE` | Tables (headers+rows or CSV) |
| `FIGURE` + `IMAGE` | Images with caption |
| `CALLOUT` | Highlighted note (info/warning/tip/note) |
| `MATH` / `IMATH` | Block / inline math → native OMML |
| `HEADER` / `FOOTER` / `PAGENUM` | Running headers, page numbers |
| `STYLE` / `STYLEDEF` | Style overrides |
| `TOC()` | Table of contents |
| `PAGEBREAK()` | Force page break |

Inline runs inside `P([...])`: `BOLD`, `ITALIC`, `UNDERLINE`, `LINK`, `FOOTNOTE`, `IMATH`.

Templates: `default`, `academic-paper`, `project-report`.

## MCP tools (remote server)

- `dsx_info` — versions and capabilities
- `dsx_language_cheatsheet` — compact reference
- `check_dsx(source, source_name?, project_files?)` — validate only
- `generate_dsx(source, output_format="docx", source_name?, project_files?)` — compile; returns base64 document

Always treat diagnostics seriously; do not ignore `ok: false`.

## Saving the result

After a successful `generate_dsx`:

```python
import base64
data = base64.b64decode(result["output_base64"])
with open("output.docx", "wb") as f:
    f.write(data)
```

Or instruct the user / host environment to write the file from the base64 payload.

## Limits & safety

- Paths are sandboxed to the project; no absolute paths outside.
- Prefer DOCX on free hosts (PDF needs LibreOffice, which is heavy).
- Keep source under a few hundred KB; large binary assets increase request size.
