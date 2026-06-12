"""Capability negotiation and server info for MCP interoperability."""

from __future__ import annotations

import logging
from typing import Any, Dict

from cad_mcp.runtime.discovery import get_server_manifest

logger = logging.getLogger("cad_mcp.runtime.capabilities")


def get_capabilities() -> Dict[str, Any]:
    """Return server-side capability set for MCP initialize negotiation."""
    manifest = get_server_manifest()
    caps = {
        "tools": bool(manifest["capabilities"]["tools"]),
        "resources": bool(manifest["capabilities"]["resources"]),
        "prompts": bool(manifest["capabilities"]["prompts"]),
        "streaming": False,
        "websocket_transport": True,
        "stdio_transport": True,
    }
    logger.info("capabilities_get ok=%s", caps)
    return caps


def negotiate_capabilities(client_capabilities: Dict[str, Any] | None) -> Dict[str, Any]:
    """
    Negotiate compatible features with the client capability declaration.

    Unsupported client requests are reported in ``unsupported_requested``.
    """
    client = client_capabilities or {}
    server = get_capabilities()
    negotiated: Dict[str, Any] = {}
    unsupported_requested: Dict[str, Any] = {}
    for key, server_value in server.items():
        requested = client.get(key, True)
        if isinstance(server_value, bool):
            requested_bool = bool(requested)
            negotiated[key] = server_value and requested_bool
            if requested_bool and not server_value:
                unsupported_requested[key] = requested
        else:
            negotiated[key] = server_value
    result = {
        "success": True,
        "client_capabilities": client,
        "server_capabilities": server,
        "negotiated_capabilities": negotiated,
        "unsupported_requested": unsupported_requested,
    }
    logger.info("capabilities_negotiate result=%s", result)
    return result


def get_server_info() -> Dict[str, Any]:
    """Return high-level runtime/server info for MCP clients and diagnostics."""
    caps = get_capabilities()
    info = {
        "name": "CAD-MCP-Server",
        "version": "1.0.0",
        "runtime": "FastMCP",
        "cad_backend": "AutoCAD COM",
        "supports_tools": caps["tools"],
        "supports_resources": caps["resources"],
        "supports_prompts": caps["prompts"],
    }
    logger.info("capabilities_server_info=%s", info)
    return info
