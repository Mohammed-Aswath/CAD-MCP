"""
AI-callable tool abstraction layer for CAD operations.

These tools are exposed to the LLM for automated CAD manipulation.
Each tool returns structured JSON for agentic reasoning.
"""

import json
import logging
from typing import Any, Dict, Optional, List

logger = logging.getLogger(__name__)
from symbol_aliases import resolve_symbol_name
from entity_manager import (
    insert_symbol,
    move_entity,
    rotate_entity,
    delete_entity,
    connect_instruments,
    get_entities,
    count_entities,
    get_drawing_details,
    get_available_symbols,
)
from schemas import (
    SymbolInsertRequest,
    MoveRequest,
    RotateRequest,
    DeleteRequest,
    ConnectRequest,
)


def _log(category: str, message: str) -> None:
    """Internal logging helper."""
    logger.info("[%s] %s", category, message)


def insert_symbol_tool(
    block_name: str,
    x: float,
    y: float,
    rotation: float = 0.0,
    layer: str = "0",
    scale: float = 500.0,
) -> Dict[str, Any]:
    """
    Insert a symbol into the drawing.
    
    Args:
        block_name: Name of symbol (e.g., '4_way_valve', 'motor', 'pump')
        x: X coordinate (world space)
        y: Y coordinate (world space)
        rotation: Rotation angle in degrees (default: 0)
        layer: Layer name (default: '0')
        scale: Symbol scale (default: 500)
    
    Returns:
        JSON with success status and entity metadata
    """
    try:
        _log("TOOL", f"Inserting {block_name} at ({x:.1f}, {y:.1f})")
        
        available = get_available_symbols()
        normalized_name = resolve_symbol_name(block_name, available)
        if normalized_name.lower() not in [s.lower() for s in available]:
            suggestion = None
            try:
                import difflib
                suggestion = difflib.get_close_matches(block_name.lower(), [s.lower() for s in available], n=1, cutoff=0.6)
                suggestion = suggestion[0] if suggestion else None
            except Exception:
                suggestion = None

            error_message = f"Unknown symbol: {block_name}."
            if suggestion:
                error_message += f" Did you mean: {suggestion}?"
            error_message += f" Available: {', '.join(available[:8])}..."
            return {
                "success": False,
                "error": error_message,
            }

        request = SymbolInsertRequest(
            block_name=normalized_name,
            x=x,
            y=y,
            rotation=rotation,
            layer=layer,
            scale=scale,
        )
        
        entity = insert_symbol(request)
        
        _log("TOOL", f"Successfully inserted {block_name} with handle {entity.handle}")
        
        return {
            "success": True,
            "message": f"Inserted {block_name}",
            "entity_handle": entity.handle,
            "position": entity.insertion_point[:2] if entity.insertion_point else None,
            "entity": entity.dict(),
        }
    
    except Exception as exc:
        _log("TOOL", f"Insert failed: {exc}")
        return {
            "success": False,
            "error": str(exc),
        }


def move_entity_tool(
    entity_handle: str,
    dx: float,
    dy: float,
    dz: float = 0.0,
) -> Dict[str, Any]:
    """
    Move an entity by a relative distance.
    
    Args:
        entity_handle: Handle of entity to move
        dx: Distance to move in X direction
        dy: Distance to move in Y direction
        dz: Distance to move in Z direction (default: 0)
    
    Returns:
        JSON with success status and updated entity metadata
    """
    try:
        _log("TOOL", f"Moving entity {entity_handle} by ({dx:.1f}, {dy:.1f}, {dz:.1f})")
        
        request = MoveRequest(handle=entity_handle, dx=dx, dy=dy, dz=dz)
        entity = move_entity(request)
        
        _log("TOOL", f"Successfully moved entity to {entity.insertion_point[:2]}")
        
        return {
            "success": True,
            "message": f"Moved entity by ({dx:.1f}, {dy:.1f})",
            "entity_handle": entity.handle,
            "new_position": entity.insertion_point[:2] if entity.insertion_point else None,
        }
    
    except Exception as exc:
        _log("TOOL", f"Move failed: {exc}")
        return {
            "success": False,
            "error": str(exc),
        }


def rotate_entity_tool(
    entity_handle: str,
    angle: float,
    base_x: float = 0.0,
    base_y: float = 0.0,
) -> Dict[str, Any]:
    """
    Rotate an entity around a base point.
    
    Args:
        entity_handle: Handle of entity to rotate
        angle: Rotation angle in degrees
        base_x: X coordinate of rotation base point
        base_y: Y coordinate of rotation base point
    
    Returns:
        JSON with success status and updated entity metadata
    """
    try:
        _log("TOOL", f"Rotating entity {entity_handle} by {angle:.1f}° around ({base_x:.1f}, {base_y:.1f})")
        
        request = RotateRequest(
            handle=entity_handle,
            angle=angle,
            base_x=base_x,
            base_y=base_y,
            base_z=0.0,
        )
        entity = rotate_entity(request)
        
        _log("TOOL", f"Successfully rotated entity to {entity.rotation or 0:.1f}°")
        
        return {
            "success": True,
            "message": f"Rotated entity by {angle:.1f}°",
            "entity_handle": entity.handle,
            "new_rotation": entity.rotation or 0.0,
        }
    
    except Exception as exc:
        _log("TOOL", f"Rotate failed: {exc}")
        return {
            "success": False,
            "error": str(exc),
        }


def delete_entity_tool(entity_handle: str) -> Dict[str, Any]:
    """
    Delete an entity from the drawing.
    
    Args:
        entity_handle: Handle of entity to delete
    
    Returns:
        JSON with success status
    """
    try:
        _log("TOOL", f"Deleting entity {entity_handle}")
        
        request = DeleteRequest(handle=entity_handle)
        result = delete_entity(request)
        
        _log("TOOL", f"Successfully deleted entity {entity_handle}")
        
        return {
            "success": True,
            "message": f"Deleted entity",
            "deleted_handle": entity_handle,
        }
    
    except Exception as exc:
        _log("TOOL", f"Delete failed: {exc}")
        return {
            "success": False,
            "error": str(exc),
        }


def connect_pipe_tool(
    start_handle: str,
    end_handle: str,
) -> Dict[str, Any]:
    """
    Connect two entities with a pipe.
    
    Args:
        start_handle: Handle of start entity
        end_handle: Handle of end entity
    
    Returns:
        JSON with success status and pipe handle
    """
    try:
        _log("TOOL", f"Connecting {start_handle} to {end_handle}")
        
        request = ConnectRequest(start_handle=start_handle, end_handle=end_handle)
        result = connect_instruments(request)
        
        _log("TOOL", f"Successfully connected with pipe {result.get('connected')}")
        
        return {
            "success": True,
            "message": "Connected entities with pipe",
            "pipe_handle": result.get("connected"),
        }
    
    except Exception as exc:
        _log("TOOL", f"Connect failed: {exc}")
        return {
            "success": False,
            "error": str(exc),
        }


def get_entities_tool() -> Dict[str, Any]:
    """
    Get all entities in the drawing.
    
    Returns:
        JSON with entity list
    """
    try:
        _log("TOOL", "Fetching all entities")
        
        entities = get_entities()
        
        entity_list = []
        for ent in entities:
            entity_list.append({
                "handle": ent.handle,
                "type": ent.entity_type,
                "block_name": ent.block_name,
                "position": ent.insertion_point[:2] if ent.insertion_point else None,
                "layer": ent.layer,
            })
        
        _log("TOOL", f"Retrieved {len(entity_list)} entities")
        
        return {
            "success": True,
            "entities": entity_list,
            "count": len(entity_list),
        }
    
    except Exception as exc:
        _log("TOOL", f"Get entities failed: {exc}")
        return {
            "success": False,
            "error": str(exc),
        }


def count_entities_tool() -> Dict[str, Any]:
    """
    Count entities in the drawing.
    
    Returns:
        JSON with entity counts by type
    """
    try:
        _log("TOOL", "Counting entities")
        
        entities = get_entities()
        
        counts: Dict[str, int] = {}
        symbol_names: Dict[str, int] = {}
        
        for ent in entities:
            # Count by type
            ent_type = ent.entity_type
            counts[ent_type] = counts.get(ent_type, 0) + 1
            
            # Count by symbol name
            if ent.block_name:
                symbol_names[ent.block_name] = symbol_names.get(ent.block_name, 0) + 1
        
        _log("TOOL", f"Entity counts: {counts}")
        
        return {
            "success": True,
            "by_type": counts,
            "by_symbol": symbol_names,
            "total": len(entities),
        }
    
    except Exception as exc:
        _log("TOOL", f"Count failed: {exc}")
        return {
            "success": False,
            "error": str(exc),
        }


def find_entity_tool(search_term: str) -> Dict[str, Any]:
    """
    Find an entity by name or block type.
    
    Args:
        search_term: Name or type to search for
    
    Returns:
        JSON with matching entities
    """
    try:
        _log("TOOL", f"Searching for '{search_term}'")
        
        entities = get_entities()
        search_lower = search_term.lower()
        
        matches = []
        for ent in entities:
            block_name = (ent.block_name or "").lower()
            if search_lower in block_name:
                matches.append({
                    "handle": ent.handle,
                    "block_name": ent.block_name,
                    "position": ent.insertion_point[:2] if ent.insertion_point else None,
                    "layer": ent.layer,
                })
        
        _log("TOOL", f"Found {len(matches)} matching entities")

        if not matches:
            return {
                "success": False,
                "error": f"No entities found matching '{search_term}'",
                "matches": [],
                "count": 0,
            }

        # Expose first match directly so planner references like
        # $step1.entity_handle resolve in later steps.
        first_match = matches[0]
        return {
            "success": True,
            "matches": matches,
            "count": len(matches),
            "entity_handle": first_match.get("handle"),
            "block_name": first_match.get("block_name"),
            "position": first_match.get("position"),
            "layer": first_match.get("layer"),
        }
    
    except Exception as exc:
        _log("TOOL", f"Search failed: {exc}")
        return {
            "success": False,
            "error": str(exc),
        }


def drawing_details_tool() -> Dict[str, Any]:
    """
    Get drawing metadata and structure.
    
    Returns:
        JSON with drawing details
    """
    try:
        _log("TOOL", "Fetching drawing details")
        
        details = get_drawing_details()
        
        return {
            "success": True,
            "document": details.document_name,
            "entity_count": details.modelspace_count,
            "block_definitions": details.block_definitions,
            "layers": details.layers,
        }
    
    except Exception as exc:
        _log("TOOL", f"Drawing details failed: {exc}")
        return {
            "success": False,
            "error": str(exc),
        }


def find_free_space_near_entity_tool(
    reference_handle: str,
    offset_x: float = 500.0,
    offset_y: float = 0.0,
) -> Dict[str, Any]:
    """
    Find a free space near a reference entity for placement.
    
    Args:
        reference_handle: Handle of reference entity
        offset_x: X offset from reference position
        offset_y: Y offset from reference position
    
    Returns:
        JSON with suggested coordinates
    """
    try:
        _log("TOOL", f"Finding free space near {reference_handle}")
        
        entities = get_entities()
        
        reference = None
        for ent in entities:
            if ent.handle == reference_handle:
                reference = ent
                break
        
        if not reference or not reference.insertion_point:
            return {
                "success": False,
                "error": f"Reference entity {reference_handle} not found or has no position",
            }
        
        suggested_x = reference.insertion_point[0] + offset_x
        suggested_y = reference.insertion_point[1] + offset_y
        
        _log("TOOL", f"Suggested placement: ({suggested_x:.1f}, {suggested_y:.1f})")
        
        return {
            "success": True,
            "position": [suggested_x, suggested_y],
            "x": suggested_x,
            "y": suggested_y,
            "reference": reference_handle,
            "offset": [offset_x, offset_y],
        }
    
    except Exception as exc:
        _log("TOOL", f"Find free space failed: {exc}")
        return {
            "success": False,
            "error": str(exc),
        }


# Tool schema definitions for LLM function calling
TOOL_SCHEMAS = [
    {
        "name": "insert_symbol",
        "description": "Insert an engineering symbol (valve, pump, motor, etc.) into the drawing at specified coordinates",
        "parameters": {
            "type": "object",
            "properties": {
                "block_name": {
                    "type": "string",
                    "description": "Symbol type: 4_way_valve, 3_way_valve, pump, motor, etc."
                },
                "x": {
                    "type": "number",
                    "description": "X coordinate in world space"
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate in world space"
                },
                "rotation": {
                    "type": "number",
                    "description": "Rotation angle in degrees (default: 0)"
                },
                "layer": {
                    "type": "string",
                    "description": "Layer name (default: '0')"
                },
                "scale": {
                    "type": "number",
                    "description": "Symbol scale (default: 500)"
                },
            },
            "required": ["block_name", "x", "y"]
        }
    },
    {
        "name": "move_entity",
        "description": "Move an entity by a relative distance",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_handle": {
                    "type": "string",
                    "description": "Handle of entity to move"
                },
                "dx": {
                    "type": "number",
                    "description": "Distance to move in X direction"
                },
                "dy": {
                    "type": "number",
                    "description": "Distance to move in Y direction"
                },
                "dz": {
                    "type": "number",
                    "description": "Distance to move in Z direction (default: 0)"
                },
            },
            "required": ["entity_handle", "dx", "dy"]
        }
    },
    {
        "name": "rotate_entity",
        "description": "Rotate an entity around a base point",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_handle": {
                    "type": "string",
                    "description": "Handle of entity to rotate"
                },
                "angle": {
                    "type": "number",
                    "description": "Rotation angle in degrees"
                },
                "base_x": {
                    "type": "number",
                    "description": "X coordinate of rotation base point (default: 0)"
                },
                "base_y": {
                    "type": "number",
                    "description": "Y coordinate of rotation base point (default: 0)"
                },
            },
            "required": ["entity_handle", "angle"]
        }
    },
    {
        "name": "delete_entity",
        "description": "Delete an entity from the drawing",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_handle": {
                    "type": "string",
                    "description": "Handle of entity to delete"
                },
            },
            "required": ["entity_handle"]
        }
    },
    {
        "name": "connect_pipe",
        "description": "Connect two entities with a pipe",
        "parameters": {
            "type": "object",
            "properties": {
                "start_handle": {
                    "type": "string",
                    "description": "Handle of start entity"
                },
                "end_handle": {
                    "type": "string",
                    "description": "Handle of end entity"
                },
            },
            "required": ["start_handle", "end_handle"]
        }
    },
    {
        "name": "get_entities",
        "description": "Get all entities in the drawing",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "count_entities",
        "description": "Count entities in the drawing and breakdown by type",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "find_entity",
        "description": "Search for entities by name or symbol type",
        "parameters": {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "Name or symbol type to search for (e.g., 'pump', 'valve')"
                },
            },
            "required": ["search_term"]
        }
    },
    {
        "name": "drawing_details",
        "description": "Get drawing metadata including layers, blocks, and entity count",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "find_free_space_near_entity",
        "description": "Find a suggested placement location near an existing entity",
        "parameters": {
            "type": "object",
            "properties": {
                "reference_handle": {
                    "type": "string",
                    "description": "Handle of reference entity"
                },
                "offset_x": {
                    "type": "number",
                    "description": "X offset from reference (default: 500)"
                },
                "offset_y": {
                    "type": "number",
                    "description": "Y offset from reference (default: 0)"
                },
            },
            "required": ["reference_handle"]
        }
    },
]


def execute_tool(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a tool by name with given parameters.
    
    Args:
        tool_name: Name of the tool
        tool_input: Dictionary of tool parameters
    
    Returns:
        Tool execution result as JSON
    """
    _log("TOOL", f"Executing {tool_name} with {tool_input}")
    
    if tool_name == "insert_symbol":
        return insert_symbol_tool(**tool_input)
    elif tool_name == "move_entity":
        return move_entity_tool(**tool_input)
    elif tool_name == "rotate_entity":
        return rotate_entity_tool(**tool_input)
    elif tool_name == "delete_entity":
        return delete_entity_tool(**tool_input)
    elif tool_name == "connect_pipe":
        return connect_pipe_tool(**tool_input)
    elif tool_name == "get_entities":
        return get_entities_tool()
    elif tool_name == "count_entities":
        return count_entities_tool()
    elif tool_name == "find_entity":
        return find_entity_tool(**tool_input)
    elif tool_name == "drawing_details":
        return drawing_details_tool()
    elif tool_name == "find_free_space_near_entity":
        return find_free_space_near_entity_tool(**tool_input)
    else:
        return {
            "success": False,
            "error": f"Unknown tool: {tool_name}",
        }
