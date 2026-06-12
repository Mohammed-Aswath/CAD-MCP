"""
Read-only MCP resources for CAD runtime state.

Resources wrap existing runtime readers (`entity_manager` + adapters) and return
JSON-safe payloads only. No state mutation paths are called here.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

# Ensure project root imports resolve the same way as runtime modules.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from entity_manager import (  # noqa: E402
    get_available_symbols,
    get_drawing_details,
    get_entities as em_get_entities,
    get_entity as em_get_entity,
    get_status,
)
from symbol_aliases import SYMBOL_ALIASES  # noqa: E402

from cad_mcp.adapters.entity_adapter import (  # noqa: E402
    serialize_drawing_details,
    serialize_entities,
    serialize_entity,
    serialize_pipe,
)

logger = logging.getLogger("cad_mcp.resources")
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _success(data: Any) -> Dict[str, Any]:
    return {"success": True, "data": data}


def _error(uri: str, message: str) -> Dict[str, Any]:
    return {"success": False, "resource": uri, "error": message}


def _run_resource(uri: str, op: Callable[[], Any]) -> Dict[str, Any]:
    """Run read-only resource access with logging + normalized payload."""
    started = time.perf_counter()
    ts = _utc_iso()
    logger.info("resource_access_start uri=%s ts=%s", uri, ts)
    try:
        payload = _success(op())
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "resource_access_ok uri=%s ts=%s duration_ms=%.2f",
            uri,
            ts,
            elapsed_ms,
        )
        return payload
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.exception(
            "resource_access_fail uri=%s ts=%s duration_ms=%.2f err=%s",
            uri,
            ts,
            elapsed_ms,
            exc,
        )
        return _error(uri, f"{type(exc).__name__}: {exc}")


def _validate_handle(handle: str, uri: str) -> str:
    candidate = (handle or "").strip()
    if not candidate:
        raise ValueError("Handle is required")
    if not _HANDLE_RE.match(candidate):
        raise ValueError(f"Invalid handle format: {candidate!r}")
    return candidate


def register_resources(mcp: Any) -> None:
    """Register read-only resources and templates on the given MCP app."""

    @mcp.resource("cad://entities")
    def entities_resource() -> Dict[str, Any]:
        """Return all tracked logical entities with topology metadata."""

        def _op() -> Dict[str, Any]:
            entities = em_get_entities()
            return {"entities": serialize_entities(entities), "count": len(entities)}

        return _run_resource("cad://entities", _op)

    @mcp.resource("cad://pipes")
    def pipes_resource() -> Dict[str, Any]:
        """Return only logical pipe entities."""

        def _op() -> Dict[str, Any]:
            entities = em_get_entities()
            serialized = serialize_entities(entities)
            pipes = [serialize_pipe(e) for e in serialized if e.get("entity_type") == "pipe"]
            return {"pipes": pipes, "count": len(pipes)}

        return _run_resource("cad://pipes", _op)

    @mcp.resource("cad://drawing")
    def drawing_resource() -> Dict[str, Any]:
        """Return drawing metadata and connection status."""

        def _op() -> Dict[str, Any]:
            details = serialize_drawing_details(get_drawing_details())
            status = get_status()
            return {
                "drawing_name": details.get("document_name"),
                "layers": details.get("layers", []),
                "blocks": details.get("block_definitions", []),
                "entity_count": details.get("modelspace_count", 0),
                "connection_status": status.get("connected", False),
                "document": status.get("document"),
            }

        return _run_resource("cad://drawing", _op)

    @mcp.resource("cad://layers")
    def layers_resource() -> Dict[str, Any]:
        """Return available layer names."""

        def _op() -> Dict[str, Any]:
            details = get_drawing_details()
            layers = sorted(str(name) for name in (details.layers or []))
            return {"layers": layers, "count": len(layers)}

        return _run_resource("cad://layers", _op)

    @mcp.resource("cad://symbols")
    def symbols_resource() -> Dict[str, Any]:
        """Return canonical symbol names and alias map."""

        def _op() -> Dict[str, Any]:
            canonical = sorted(get_available_symbols())
            aliases = dict(sorted((SYMBOL_ALIASES or {}).items()))
            return {"canonical": canonical, "aliases": aliases, "count": len(canonical)}

        return _run_resource("cad://symbols", _op)

    @mcp.resource("cad://selection/current")
    def selection_current_resource() -> Dict[str, Any]:
        """
        Return current selection context.

        Runtime does not currently expose selection read API, so this remains a
        deterministic safe empty payload until such a reader is added.
        """

        def _op() -> Dict[str, Any]:
            return {"selection": [], "count": 0, "available": False}

        return _run_resource("cad://selection/current", _op)

    @mcp.resource("cad://entity/{handle}")
    def entity_by_handle_resource(handle: str) -> Dict[str, Any]:
        """Return a single logical entity by handle."""

        def _op() -> Dict[str, Any]:
            clean = _validate_handle(handle, "cad://entity/{handle}")
            entity = em_get_entity(clean)
            return {"entity": serialize_entity(entity)}

        return _run_resource("cad://entity/{handle}", _op)

    @mcp.resource("cad://pipe/{handle}")
    def pipe_by_handle_resource(handle: str) -> Dict[str, Any]:
        """Return a single pipe entity by logical handle."""

        def _op() -> Dict[str, Any]:
            clean = _validate_handle(handle, "cad://pipe/{handle}")
            entity = serialize_entity(em_get_entity(clean))
            if entity.get("entity_type") != "pipe":
                raise ValueError(f"Entity {clean!r} is not a pipe")
            return {"pipe": serialize_pipe(entity)}

        return _run_resource("cad://pipe/{handle}", _op)

    @mcp.resource("cad://layer/{name}")
    def layer_entities_resource(name: str) -> Dict[str, Any]:
        """Return entities within the requested layer name."""

        def _op() -> Dict[str, Any]:
            layer = (name or "").strip()
            if not layer:
                raise ValueError("Layer name is required")
            entities = serialize_entities(em_get_entities())
            on_layer = [e for e in entities if str(e.get("layer") or "") == layer]
            return {"layer": layer, "entities": on_layer, "count": len(on_layer)}

        return _run_resource("cad://layer/{name}", _op)

    logger.info(
        "Registered MCP resources: cad://entities, cad://pipes, cad://drawing, "
        "cad://layers, cad://symbols, cad://selection/current, cad://entity/{handle}, "
        "cad://pipe/{handle}, cad://layer/{name}"
    )
