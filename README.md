# DSX MCP Server (Remote)

Remote **Model Context Protocol** server that exposes [DSX (DocScript AI)](https://github.com/) tools to Claude and other MCP clients.

DSX is a declarative language that compiles to professional **DOCX** (and optionally PDF) documents with native Word equations, tables, callouts, lists, and more.

## Tools

| Tool | Description |
|------|-------------|
| `check_dsx` | Validate DSX source (no render) |
| `generate_dsx` | Compile DSX → DOCX or PDF (returns base64) |
| `dsx_info` | Version & capability summary |
| `dsx_language_cheatsheet` | Compact language reference |

## Quick start (local)

```bash
# From this directory
pip install -r requirements.txt
# Optional: install the vendored package in editable mode
pip install -e .   # if you add a pyproject that points at src/

# Local stdio (Claude Desktop / Claude Code)
MCP_TRANSPORT=stdio python server.py

# Remote-style HTTP (default)
python server.py
# → Streamable HTTP on http://0.0.0.0:8000
```

Endpoint for remote clients is typically:

```
https://<your-host>/mcp
```

(Exact path depends on FastMCP version; most current versions use `/mcp`.)

## Connect to Claude

### Claude Code (CLI)

```bash
claude mcp add --transport http dsx https://YOUR-HOST/mcp
```

### Claude Desktop / Web (custom connector)

1. **Customize → Connectors → Add custom connector**
2. Paste: `https://YOUR-HOST/mcp`
3. Free Claude accounts are limited to one custom connector.

### Project-level `.mcp.json`

```json
{
  "mcpServers": {
    "dsx": {
      "type": "http",
      "url": "https://YOUR-HOST/mcp"
    }
  }
}
```

## Skill for Claude

Copy the folder `skill-dsx/` into your Claude skills directory (or use with Claude Code skills). The `SKILL.md` teaches the agent when and how to call the MCP tools and how to write valid DSX.

## Free hosting recommendations

See the table below and the detailed guide in the main response / `docs/hosting.md`.

| Platform | Free tier notes | Difficulty |
|----------|-----------------|------------|
| **Render** | Free web service (spins down after idle) | Easy |
| **Fly.io** | Generous free allowance, always-on optional | Medium |
| **Railway** | Trial / limited free credits | Easy |
| **Google Cloud Run** | Free tier with scale-to-zero | Medium |
| **Hugging Face Spaces** | Free CPU, good for demos | Easy |

**Recommended for most users: Render free** or **Fly.io**.

## Security notes

- Do **not** expose an unauthenticated public MCP server if it can write to disks or call privileged APIs. This server only returns document bytes; it does not write to the host filesystem.
- For shared use, put a bearer token or OAuth in front (FastMCP / reverse proxy).
- Prefer DOCX only on free tiers (LibreOffice for PDF is large and slow to install).

## License

DSX core follows its original license (see `src/dsx` / upstream). This MCP wrapper is provided as-is for integration with Claude.
