"""
MCP tool registrations — thin wrappers around existing runtime only.

Calls :mod:`entity_manager`, :mod:`tool_registry` (for agent-aligned tools),
and adapters for JSON-safe output. No direct COM access.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict

from pydantic import ValidationError

# Repository root (parent of the ``cad_mcp`` package)
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from entity_manager import (  # noqa: E402
    connect_instruments,
    delete_entity as em_delete_entity,
    get_drawing_details,
    get_entities as em_get_entities,
    move_entity as em_move_entity,
    rotate_entity as em_rotate_entity,
)
from schemas import (  # noqa: E402
    ConnectRequest,
    DeleteRequest,
    MoveRequest,
    RotateRequest,
    SymbolInsertRequest,
)
from tool_registry import execute_tool  # noqa: E402

from cad_mcp.adapters.entity_adapter import (  # noqa: E402
    serialize_drawing_details,
    serialize_entities,
    serialize_entity,
)
from cad_mcp.adapters.execution_adapter import run_tool  # noqa: E402
from cad_mcp.adapters.pipe_adapter import wrap_connect_result  # noqa: E402

logger = logging.getLogger("cad_mcp.tools")


def _validation_error_payload(exc: ValidationError, tool: str) -> Dict[str, Any]:
    parts = [f"{'.'.join(str(x) for x in e.get('loc', ()) or ()): {e.get('msg')}}" for e in exc.errors()]
    return {"success": False, "error": "; ".join(parts) or str(exc), "tool": tool}


def _unwrap_registry(raw: Dict[str, Any], tool: str) -> Dict[str, Any]:
    """Raise if registry/agent tool reported failure; otherwise return payload."""
    if raw.get("success") is False:
        raise ValueError(raw.get("error", f"{tool} failed"))
    return {k: v for k, v in raw.items() if k != "success"}


def register_tools(mcp: Any) -> None:
    """Register all CAD MCP tools on the given FastMCP instance."""

    @mcp.tool()
    def insert_symbol(
        block_name: str,
        x: float,
        y: float,
        rotation: float = 0.0,
        layer: str = "0",
        scale: float = 500.0,
    ) -> Dict[str, Any]:
        """
        Insert a block/symbol at world coordinates.

        Delegates to :func:`tool_registry.execute_tool` so symbol alias
        resolution matches the Gemini agent and REST stack.
        """
        try:
            req = SymbolInsertRequest(
                block_name=block_name,
                x=x,
                y=y,
                rotation=rotation,
                layer=layer,
                scale=scale,
            )
        except ValidationError as exc:
            return _validation_error_payload(exc, "insert_symbol")

        def _impl() -> Dict[str, Any]:
            raw = execute_tool("insert_symbol", req.model_dump())
            return _unwrap_registry(raw, "insert_symbol")

        return run_tool("insert_symbol", _impl)

    @mcp.tool()
    def move_entity(handle: str, dx: float, dy: float, dz: float = 0.0) -> Dict[str, Any]:
        """Move an entity by delta in drawing units."""

        try:
            req = MoveRequest(handle=handle, dx=dx, dy=dy, dz=dz)
        except ValidationError as exc:
            return _validation_error_payload(exc, "move_entity")

        def _impl() -> Dict[str, Any]:
            ent = em_move_entity(req)
            return serialize_entity(ent)

        return run_tool("move_entity", _impl)

    @mcp.tool()
    def rotate_entity(
        handle: str,
        angle: float,
        base_x: float = 0.0,
        base_y: float = 0.0,
        base_z: float = 0.0,
    ) -> Dict[str, Any]:
        """Rotate an entity around a base point (angle in degrees)."""

        try:
            req = RotateRequest(
                handle=handle,
                angle=angle,
                base_x=base_x,
                base_y=base_y,
                base_z=base_z,
            )
        except ValidationError as exc:
            return _validation_error_payload(exc, "rotate_entity")

        def _impl() -> Dict[str, Any]:
            ent = em_rotate_entity(req)
            return serialize_entity(ent)

        return run_tool("rotate_entity", _impl)

    @mcp.tool()
    def delete_entity(handle: str) -> Dict[str, Any]:
        """Delete an entity by logical handle."""

        try:
            req = DeleteRequest(handle=handle)
        except ValidationError as exc:
            return _validation_error_payload(exc, "delete_entity")

        def _impl() -> Dict[str, Any]:
            return em_delete_entity(req)

        return run_tool("delete_entity", _impl)

    @mcp.tool()
    def connect_pipe(start_handle: str, end_handle: str) -> Dict[str, Any]:
        """Create a pipe between two instrument entities."""

        try:
            req = ConnectRequest(start_handle=start_handle, end_handle=end_handle)
        except ValidationError as exc:
            return _validation_error_payload(exc, "connect_pipe")

        def _impl() -> Dict[str, Any]:
            raw = connect_instruments(req)
            return wrap_connect_result(raw)

        return run_tool("connect_pipe", _impl)

    @mcp.tool()
    def get_entities() -> Dict[str, Any]:
        """Return all tracked entities as JSON-safe metadata."""

        def _impl() -> Dict[str, Any]:
            entities = em_get_entities()
            return {"entities": serialize_entities(entities), "count": len(entities)}

        return run_tool("get_entities", _impl)

    @mcp.tool()
    def count_entities() -> Dict[str, Any]:
        """
        Return entity counts by type and symbol (same semantics as the agent
        ``count_entities`` tool).
        """

        def _impl() -> Dict[str, Any]:
            raw = execute_tool("count_entities", {})
            return _unwrap_registry(raw, "count_entities")

        return run_tool("count_entities", _impl)

    @mcp.tool()
    def find_entity(search_term: str) -> Dict[str, Any]:
        """Search entities by block name / type substring (agent semantics)."""

        def _impl() -> Dict[str, Any]:
            raw = execute_tool("find_entity", {"search_term": search_term})
            return _unwrap_registry(raw, "find_entity")

        return run_tool("find_entity", _impl)

    @mcp.tool()
    def drawing_details() -> Dict[str, Any]:
        """Return drawing metadata (document, layers, blocks, modelspace count)."""

        def _impl() -> Dict[str, Any]:
            details = get_drawing_details()
            return serialize_drawing_details(details)

        return run_tool("drawing_details", _impl)

    logger.info("Registered 9 CAD MCP tools on FastMCP instance.")
