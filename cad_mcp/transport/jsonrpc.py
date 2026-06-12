"""
JSON-RPC transport (placeholder).

The official MCP Python SDK uses structured messages over stdio, SSE, or
streamable HTTP rather than raw JSON-RPC POST. This module reserves a future
adapter if a custom JSON-RPC bridge is required (e.g. legacy clients).

TODO:
    - Define a thin facade mapping JSON-RPC payloads to the same tool
      dispatch used by :mod:`mcp.tools`.
    - Keep all CAD invocation paths delegated to :mod:`entity_manager` /
      :mod:`tool_registry` only.
"""

from __future__ import annotations

# Placeholder — no implementation yet.
