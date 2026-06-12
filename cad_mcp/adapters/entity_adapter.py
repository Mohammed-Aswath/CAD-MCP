"""
Convert AutoCAD / Pydantic runtime models into MCP-safe JSON structures.

No COM objects are passed through: only primitives, lists, and dicts.

Imports ``schemas`` from the repository root (same as ``entity_manager``).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

# Repository root (parent of ``mcp/``)
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

def _model_to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "dict"):
        return obj.dict()
    if isinstance(obj, (list, tuple)):
        return [_model_to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _model_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def serialize_entity(entity: Any) -> Dict[str, Any]:
    """Serialize a single EntityMetadata (or dict-like) to plain JSON dict."""
    data = _model_to_dict(entity)
    if not isinstance(data, dict):
        return {"handle": str(entity), "entity_type": "unknown", "raw": data}
    ip = data.get("insertion_point")
    if isinstance(ip, (list, tuple)):
        data["insertion_point"] = [float(x) for x in ip[:3]]
    return data


def serialize_entities(entities: List[Any]) -> List[Dict[str, Any]]:
    return [serialize_entity(e) for e in entities]


def serialize_pipe(entity_or_dict: Any) -> Dict[str, Any]:
    """
    Serialize a pipe logical entity (from registry / EntityMetadata).

    Pipes use entity_type ``pipe`` and endpoint logical handles.
    """
    d = serialize_entity(entity_or_dict)
    if d.get("entity_type") != "pipe":
        d.setdefault("entity_type", "pipe")
    return d


def serialize_drawing_details(details: Any) -> Dict[str, Any]:
    """Serialize DrawingDetails model to JSON dict."""
    return _model_to_dict(details)
