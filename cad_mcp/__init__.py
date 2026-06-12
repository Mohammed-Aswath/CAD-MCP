"""
CAD MCP adapter package.

Exposes :data:`cad_mcp.runtime.bridge.mcp` (FastMCP) for transports and tests.

NOTE: The runtime lives in ``cad_mcp/runtime``. :mod:`cad_mcp._sdk` safely
loads the SDK ``FastMCP`` class while avoiding local import shadowing issues.
"""

from __future__ import annotations

from cad_mcp.runtime.bridge import mcp

__all__ = ["mcp"]