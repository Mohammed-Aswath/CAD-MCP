import logging
from typing import Any, Callable, Dict

from agent_tools import (
    connect_pipe_tool,
    count_entities_tool,
    delete_entity_tool,
    drawing_details_tool,
    find_entity_tool,
    find_free_space_near_entity_tool,
    get_entities_tool,
    insert_symbol_tool,
    move_entity_tool,
    rotate_entity_tool,
    TOOL_SCHEMAS as AGENT_TOOL_SCHEMAS,
)

TOOLS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "insert_symbol": insert_symbol_tool,
    "move_entity": move_entity_tool,
    "rotate_entity": rotate_entity_tool,
    "delete_entity": delete_entity_tool,
    "connect_pipe": connect_pipe_tool,
    "get_entities": get_entities_tool,
    "count_entities": count_entities_tool,
    "find_entity": find_entity_tool,
    "drawing_details": drawing_details_tool,
    "find_free_space_near_entity": find_free_space_near_entity_tool,
}

TOOL_SCHEMAS = AGENT_TOOL_SCHEMAS

logger = logging.getLogger(__name__)


def _log(category: str, message: str) -> None:
    logger.info("[%s] %s", category, message)


def _normalize_tool_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {"success": False, "error": "Invalid tool result"}

    if "entity_handle" in result and "handle" not in result:
        result["handle"] = result["entity_handle"]
    if "pipe_handle" in result and "handle" not in result:
        result["handle"] = result["pipe_handle"]
    if "deleted_handle" in result and "handle" not in result:
        result["handle"] = result["deleted_handle"]

    return result


def execute_tool(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    _log("TOOLS", f"Dispatching tool {tool_name} with input {tool_input}")
    tool = TOOLS.get(tool_name)
    if not tool:
        return {
            "success": False,
            "error": f"Unknown tool: {tool_name}",
        }
    try:
        result = tool(**tool_input)
        normalized = _normalize_tool_result(result)
        return normalized
    except Exception as exc:
        _log("TOOLS", f"Tool execution error for {tool_name}: {exc}")
        return {
            "success": False,
            "error": str(exc),
        }
