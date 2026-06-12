"""
Thin helpers for pipe-related MCP payloads.

Uses the same serialization rules as ``entity_adapter``; keeps pipe metadata
explicit for clients.
"""

from __future__ import annotations

from typing import Any, Dict

from .entity_adapter import serialize_pipe


def wrap_connect_result(connected_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize ``connect_instruments`` return value ``{\"connected\": pipe_handle}``.

    The full pipe entity can be fetched later via ``get_entities`` if needed.
    """
    return {"connected": connected_payload.get("connected"), "raw": connected_payload}


def pipe_from_entity_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a pipe-shaped entity registry entry."""
    return serialize_pipe(data)
