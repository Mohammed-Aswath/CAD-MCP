"""
CAD context builder for AI reasoning.

Converts raw CAD state into AI-readable semantic summaries.
"""

import logging
from typing import Dict, List, Any, Optional

from entity_manager import get_entities, get_drawing_details

logger = logging.getLogger(__name__)


def _log(category: str, message: str) -> None:
    """Internal logging helper."""
    logger.info("[%s] %s", category, message)


def get_cad_context() -> Dict[str, Any]:
    """
    Build complete CAD state context for AI reasoning.
    
    Returns:
        Dictionary with entities, topology, counts, and drawing details
    """
    try:
        _log("CONTEXT", "Building CAD context")
        
        entities = get_entities()
        drawing = get_drawing_details()
        
        # Build entity list
        entity_list = []
        for ent in entities:
            entity_list.append({
                "handle": ent.handle,
                "type": ent.entity_type,
                "block_name": ent.block_name,
                "position": ent.insertion_point[:2] if ent.insertion_point else None,
                "rotation": ent.rotation or 0,
                "layer": ent.layer,
                "scale": ent.scale or 100,
            })
        
        # Count entities by type and symbol
        type_counts: Dict[str, int] = {}
        symbol_counts: Dict[str, int] = {}
        
        for ent in entities:
            # By type
            ent_type = ent.entity_type
            type_counts[ent_type] = type_counts.get(ent_type, 0) + 1
            
            # By symbol name
            if ent.block_name:
                symbol_counts[ent.block_name] = symbol_counts.get(ent.block_name, 0) + 1
        
        # Build topology connections
        connections = []
        for ent in entities:
            if ent.entity_type == "pipe" and ent.start_handle and ent.end_handle:
                connections.append({
                    "pipe": ent.handle,
                    "from": ent.start_handle,
                    "to": ent.end_handle,
                })
        
        # Build context
        context = {
            "drawing": {
                "name": drawing.document_name,
                "entity_count": drawing.modelspace_count,
                "layers": drawing.layers,
                "blocks": drawing.block_definitions,
            },
            "entities": entity_list,
            "topology": connections,
            "counts": {
                "by_type": type_counts,
                "by_symbol": symbol_counts,
                "total": len(entities),
            },
        }
        
        _log("CONTEXT", f"Built context with {len(entity_list)} entities")
        
        return context
    
    except Exception as exc:
        _log("CONTEXT", f"Context building failed: {exc}")
        return {
            "error": str(exc),
        }


def build_context_summary() -> str:
    """
    Build a natural language summary of the current CAD state.
    
    Returns:
        Human-readable summary for AI reasoning
    """
    try:
        context = get_cad_context()
        
        if "error" in context:
            return f"Error: {context['error']}"
        
        counts = context.get("counts", {})
        symbol_counts = counts.get("by_symbol", {})
        connections = context.get("topology", [])
        
        # Build summary text
        parts = []
        
        parts.append(f"Drawing: {context.get('drawing', {}).get('name', 'unknown')}")
        parts.append(f"Total entities: {counts.get('total', 0)}")
        
        # Symbol breakdown
        if symbol_counts:
            parts.append("\nSymbols present:")
            for symbol, count in sorted(symbol_counts.items()):
                parts.append(f"  - {symbol}: {count}")
        
        # Connection summary
        if connections:
            parts.append(f"\nPipe connections: {len(connections)}")
            for conn in connections[:5]:  # Show first 5
                from_symbol = None
                to_symbol = None
                
                # Find symbol names
                for ent in context.get("entities", []):
                    if ent["handle"] == conn.get("from"):
                        from_symbol = ent.get("block_name", "unknown")
                    if ent["handle"] == conn.get("to"):
                        to_symbol = ent.get("block_name", "unknown")
                
                parts.append(f"  - {from_symbol} → {to_symbol}")
            
            if len(connections) > 5:
                parts.append(f"  ... and {len(connections) - 5} more connections")
        
        summary = "\n".join(parts)
        _log("CONTEXT", f"Generated summary ({len(summary)} chars)")
        
        return summary
    
    except Exception as exc:
        _log("CONTEXT", f"Summary building failed: {exc}")
        return f"Error building summary: {exc}"


def find_entity_by_symbol(symbol_name: str) -> Optional[Dict[str, Any]]:
    """
    Find the first entity matching a symbol name.
    
    Args:
        symbol_name: Symbol type to search for
    
    Returns:
        Entity dict or None
    """
    try:
        context = get_cad_context()
        
        if "error" in context:
            return None
        
        search_lower = symbol_name.lower()
        
        for ent in context.get("entities", []):
            if ent.get("block_name", "").lower() == search_lower:
                return ent
        
        return None
    
    except Exception as exc:
        _log("CONTEXT", f"Entity search failed: {exc}")
        return None


def find_all_entities_by_symbol(symbol_name: str) -> List[Dict[str, Any]]:
    """
    Find all entities matching a symbol name.
    
    Args:
        symbol_name: Symbol type to search for
    
    Returns:
        List of matching entity dicts
    """
    try:
        context = get_cad_context()
        
        if "error" in context:
            return []
        
        search_lower = symbol_name.lower()
        matches = []
        
        for ent in context.get("entities", []):
            if ent.get("block_name", "").lower() == search_lower:
                matches.append(ent)
        
        return matches
    
    except Exception as exc:
        _log("CONTEXT", f"Entities search failed: {exc}")
        return []


def get_entity_by_handle(handle: str) -> Optional[Dict[str, Any]]:
    """
    Get entity by handle.
    
    Args:
        handle: Entity handle
    
    Returns:
        Entity dict or None
    """
    try:
        context = get_cad_context()
        
        if "error" in context:
            return None
        
        for ent in context.get("entities", []):
            if ent.get("handle") == handle:
                return ent
        
        return None
    
    except Exception as exc:
        _log("CONTEXT", f"Handle lookup failed: {exc}")
        return None


def find_nearest_entity(
    reference_position: tuple,
    symbol_name: Optional[str] = None,
    max_distance: float = 10000.0,
) -> Optional[Dict[str, Any]]:
    """
    Find the nearest entity to a position, optionally filtered by symbol.
    
    Args:
        reference_position: (x, y) tuple
        symbol_name: Optional filter by symbol type
        max_distance: Maximum search distance
    
    Returns:
        Nearest entity dict or None
    """
    try:
        context = get_cad_context()
        
        if "error" in context:
            return None
        
        nearest = None
        nearest_dist = max_distance
        
        for ent in context.get("entities", []):
            # Filter by symbol if specified
            if symbol_name and ent.get("block_name", "").lower() != symbol_name.lower():
                continue
            
            pos = ent.get("position")
            if not pos:
                continue
            
            # Compute distance
            dx = pos[0] - reference_position[0]
            dy = pos[1] - reference_position[1]
            dist = (dx * dx + dy * dy) ** 0.5
            
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = ent
        
        return nearest
    
    except Exception as exc:
        _log("CONTEXT", f"Nearest entity search failed: {exc}")
        return None


def get_connections_for_entity(entity_handle: str) -> List[Dict[str, Any]]:
    """
    Get all pipe connections for an entity.
    
    Args:
        entity_handle: Handle of entity
    
    Returns:
        List of connection dicts
    """
    try:
        context = get_cad_context()
        
        if "error" in context:
            return []
        
        connections = []
        
        for conn in context.get("topology", []):
            if conn.get("from") == entity_handle or conn.get("to") == entity_handle:
                connections.append(conn)
        
        return connections
    
    except Exception as exc:
        _log("CONTEXT", f"Connection lookup failed: {exc}")
        return []


def is_entity_connected(entity_handle: str) -> bool:
    """
    Check if an entity has any pipe connections.
    
    Args:
        entity_handle: Handle of entity
    
    Returns:
        True if entity has connections
    """
    return len(get_connections_for_entity(entity_handle)) > 0


def get_symbol_count(symbol_name: str) -> int:
    """
    Count entities of a specific symbol type.
    
    Args:
        symbol_name: Symbol type to count
    
    Returns:
        Count of matching entities
    """
    try:
        context = get_cad_context()
        
        if "error" in context:
            return 0
        
        counts = context.get("counts", {}).get("by_symbol", {})
        return counts.get(symbol_name, 0)
    
    except Exception as exc:
        _log("CONTEXT", f"Symbol count failed: {exc}")
        return 0


def format_entity_for_ai(entity: Dict[str, Any]) -> str:
    """
    Format entity as a string for AI reasoning.
    
    Args:
        entity: Entity dict
    
    Returns:
        Formatted string
    """
    parts = []
    parts.append(f"Entity: {entity.get('block_name', 'unknown')}")
    
    pos = entity.get("position")
    if pos:
        parts.append(f"Position: ({pos[0]:.0f}, {pos[1]:.0f})")
    
    rot = entity.get("rotation", 0)
    if rot != 0:
        parts.append(f"Rotation: {rot:.0f}°")
    
    parts.append(f"Handle: {entity.get('handle', '?')}")
    
    return " | ".join(parts)
