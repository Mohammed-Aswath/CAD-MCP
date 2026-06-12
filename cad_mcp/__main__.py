"""Allow ``python -m cad_mcp`` to launch the stdio MCP server."""

from __future__ import annotations

from cad_mcp.transport.stdio_transport import run_stdio

if __name__ == "__main__":
    run_stdio()
