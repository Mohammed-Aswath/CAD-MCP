"""MCP discovery helpers for tools/resources/prompts and server manifest."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Dict, List

from cad_mcp.runtime.bridge import mcp

logger = logging.getLogger("cad_mcp.runtime.discovery")


def _run_maybe_async(value: Any) -> Any:
    """Resolve coroutine values in sync contexts."""
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def _obj_to_manifest(obj: Any) -> Dict[str, Any]:
    """Best-effort object normalization for MCP metadata exposure."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return obj
    name = getattr(obj, "name", None) or getattr(obj, "id", None)
    description = getattr(obj, "description", None)
    uri = getattr(obj, "uri", None)
    return {
        "name": name or str(obj),
        "description": description,
        "uri": uri,
    }


def get_tool_manifest() -> List[Dict[str, Any]]:
    """Enumerate registered MCP tools dynamically from shared FastMCP app."""
    logger.info("discovery_get_tool_manifest_start")
    items = _run_maybe_async(mcp.list_tools())
    manifest = [_obj_to_manifest(item) for item in items]
    logger.info("discovery_get_tool_manifest_ok count=%s", len(manifest))
    return manifest


def get_resource_manifest() -> Dict[str, List[Dict[str, Any]]]:
    """
    Enumerate static resources and dynamic resource templates.

    Returns both categories for interoperability diagnostics.
    """
    logger.info("discovery_get_resource_manifest_start")
    resources = _run_maybe_async(mcp.list_resources())
    templates = _run_maybe_async(mcp.list_resource_templates())
    manifest = {
        "resources": [_obj_to_manifest(item) for item in resources],
        "templates": [_obj_to_manifest(item) for item in templates],
    }
    logger.info(
        "discovery_get_resource_manifest_ok resources=%s templates=%s",
        len(manifest["resources"]),
        len(manifest["templates"]),
    )
    return manifest


def get_prompt_manifest() -> List[Dict[str, Any]]:
    """Enumerate registered MCP prompts dynamically."""
    logger.info("discovery_get_prompt_manifest_start")
    items = _run_maybe_async(mcp.list_prompts())
    manifest = [_obj_to_manifest(item) for item in items]
    logger.info("discovery_get_prompt_manifest_ok count=%s", len(manifest))
    return manifest


def get_server_manifest() -> Dict[str, Any]:
    """Return dynamic interoperability manifest for MCP clients."""
    logger.info("discovery_get_server_manifest_start")
    tools = get_tool_manifest()
    resources = get_resource_manifest()
    prompts = get_prompt_manifest()
    out = {
        "server_name": "CAD-MCP-Server",
        "capabilities": {
            "tools": len(tools) > 0,
            "resources": len(resources["resources"]) > 0 or len(resources["templates"]) > 0,
            "prompts": len(prompts) > 0,
        },
        "tool_count": len(tools),
        "resource_count": len(resources["resources"]),
        "resource_template_count": len(resources["templates"]),
        "prompt_count": len(prompts),
    }
    logger.info("discovery_get_server_manifest_ok payload=%s", out)
    return out
