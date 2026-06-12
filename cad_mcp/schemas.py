"""Pydantic schemas for normalized MCP tool responses."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class MCPToolError(BaseModel):
    """Structured error returned by MCP tools (failure path)."""

    success: bool = Field(default=False, description="Always false for errors")
    error: str = Field(..., description="Human-readable error message")
    tool: str = Field(..., description="Tool name that failed")


class MCPToolSuccess(BaseModel):
    """Structured success wrapper."""

    success: bool = Field(default=True, description="Always true on success")
    result: Any = Field(..., description="JSON-serializable payload")


MCPToolResponse = Union[MCPToolSuccess, MCPToolError]

# Back-compat alias for docs / type checkers
MCPErrorResponse = MCPToolError


class MCPEntityResponse(BaseModel):
    """Single entity in MCP-safe form."""

    handle: str
    entity_type: str
    block_name: Optional[str] = None
    layer: Optional[str] = None
    insertion_point: Optional[List[float]] = None
    rotation: Optional[float] = None
    scale: Optional[float] = None
    connected_entities: Optional[List[str]] = None
    start_handle: Optional[str] = None
    end_handle: Optional[str] = None
    segment_handles: Optional[List[str]] = None
    route_points: Optional[List[List[float]]] = None
    metadata: Optional[Dict[str, Any]] = None


class MCPPipeResponse(BaseModel):
    """Logical pipe summary for clients."""

    handle: str
    entity_type: str = "pipe"
    start_handle: Optional[str] = None
    end_handle: Optional[str] = None
    segment_handles: Optional[List[str]] = None


class MCPDrawingDetailsResponse(BaseModel):
    """Drawing metadata exposed to MCP."""

    document_name: str
    modelspace_count: int
    block_definitions: List[str]
    layers: List[str]


class MCPResourceError(BaseModel):
    """Structured error envelope for MCP resource access."""

    success: bool = Field(default=False)
    resource: str
    error: str


class MCPResourceSuccess(BaseModel):
    """Structured success envelope for MCP resource access."""

    success: bool = Field(default=True)
    data: Any


MCPResourceResponse = Union[MCPResourceSuccess, MCPResourceError]