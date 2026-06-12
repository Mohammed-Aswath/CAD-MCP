"""
Plan Validation and Normalization Layer.

This module validates and normalizes planner output to ensure:
- Tools exist and have correct parameters
- Arguments match tool schemas
- Symbols are available in CAD
- Variable references are valid
- Unsupported expressions are detected
- Safe automatic corrections are applied
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from execution_models import ExecutionPlan, ExecutionStep

logger = logging.getLogger(__name__)


def _log(category: str, message: str) -> None:
    """Internal logging helper."""
    logger.info("[%s] %s", category, message)


# Argument aliases mapping for known misnamings
ARG_ALIASES = {
    "insert_symbol": {
        "name": "block_name",
        "symbol": "block_name",
        "symbol_name": "block_name",
        "position_x": "x",
        "position_y": "y",
        "pos_x": "x",
        "pos_y": "y",
        "loc_x": "x",
        "loc_y": "y",
        "angle": "rotation",
    },
    "move_entity": {
        "handle": "entity_handle",
        "entity": "entity_handle",
        "entity_id": "entity_handle",
        "x_offset": "dx",
        "y_offset": "dy",
        "z_offset": "dz",
        "distance_x": "dx",
        "distance_y": "dy",
    },
    "rotate_entity": {
        "handle": "entity_handle",
        "entity": "entity_handle",
        "entity_id": "entity_handle",
        "rotation_angle": "angle",
        "base_point_x": "base_x",
        "base_point_y": "base_y",
        "center_x": "base_x",
        "center_y": "base_y",
    },
    "delete_entity": {
        "handle": "entity_handle",
        "entity": "entity_handle",
        "entity_id": "entity_handle",
        "target": "entity_handle",
    },
    "connect_pipe": {
        "entity1_id": "start_handle",
        "entity1_handle": "start_handle",
        "from_entity": "start_handle",
        "entity2_id": "end_handle",
        "entity2_handle": "end_handle",
        "to_entity": "end_handle",
        "from": "start_handle",
        "to": "end_handle",
    },
    "find_entity": {
        "block_name": "search_term",
        "name": "search_term",
        "query": "search_term",
        "symbol_name": "search_term",
        "symbol": "search_term",
    },
    "find_free_space_near_entity": {
        "handle": "reference_handle",
        "entity": "reference_handle",
        "entity_id": "reference_handle",
        "reference_entity": "reference_handle",
        "offset_left": "offset_x",
        "offset_right": "offset_x",
        "offset_up": "offset_y",
        "offset_down": "offset_y",
    },
}

# Tool schemas for validation (maps tool name to required and optional fields)
TOOL_VALIDATION_SCHEMA = {
    "insert_symbol": {
        "required": ["block_name", "x", "y"],
        "optional": ["rotation", "layer", "scale"],
        "type_hints": {"x": "number", "y": "number", "rotation": "number", "scale": "number"}
    },
    "move_entity": {
        "required": ["entity_handle", "dx", "dy"],
        "optional": ["dz"],
        "type_hints": {"dx": "number", "dy": "number", "dz": "number"}
    },
    "rotate_entity": {
        "required": ["entity_handle", "angle"],
        "optional": ["base_x", "base_y"],
        "type_hints": {"angle": "number", "base_x": "number", "base_y": "number"}
    },
    "delete_entity": {
        "required": ["entity_handle"],
        "optional": [],
        "type_hints": {}
    },
    "connect_pipe": {
        "required": ["start_handle", "end_handle"],
        "optional": [],
        "type_hints": {}
    },
    "get_entities": {
        "required": [],
        "optional": [],
        "type_hints": {}
    },
    "count_entities": {
        "required": [],
        "optional": [],
        "type_hints": {}
    },
    "find_entity": {
        "required": ["search_term"],
        "optional": [],
        "type_hints": {}
    },
    "drawing_details": {
        "required": [],
        "optional": [],
        "type_hints": {}
    },
    "find_free_space_near_entity": {
        "required": ["reference_handle"],
        "optional": ["offset_x", "offset_y"],
        "type_hints": {"offset_x": "number", "offset_y": "number"}
    },
}


def _detect_unsupported_expressions(value: Any) -> Optional[str]:
    """
    Detect unsupported expressions in arguments.
    
    Returns None if valid, or error message if invalid expression detected.
    """
    if not isinstance(value, str):
        return None
    
    # Check for arithmetic expressions
    if any(op in value for op in ["+", "-", "*", "/", "%"]):
        if re.search(r'\$step\d+\.\w+\s*[\+\-\*/]\s*\d+', value):
            return f"Unsupported arithmetic expression: {value}. Use find_free_space_near_entity instead."
    
    # Check for unsupported function-like syntax
    if re.search(r'\w+\([^)]*\)', value) and "$" in value:
        return f"Unsupported function call: {value}. Use available tools instead."
    
    # Check for array-like coordinate syntax
    if re.search(r'\[\s*\d+\s*,\s*\d+\s*\]', value):
        return f"Unsupported array syntax: {value}. Use separate x, y parameters."
    
    return None


def validate_and_normalize_step(
    step: Dict[str, Any],
    available_symbols: List[str],
    prior_step_results: Dict[str, Any]
) -> Tuple[bool, ExecutionStep, Optional[str]]:
    """
    Validate and normalize a single execution step.
    
    Args:
        step: Raw step from planner ({"tool": "...", "args": {...}})
        available_symbols: List of valid symbols in CAD
        prior_step_results: Results from prior steps (step1, step2, etc.)
    
    Returns:
        (is_valid, normalized_step, error_message)
    """
    tool_name = step.get("tool", "").strip().lower()
    args = step.get("args", {})
    
    if not tool_name:
        return False, ExecutionStep(tool="", args={}), "Missing tool name"
    
    # Validate tool exists
    if tool_name not in TOOL_VALIDATION_SCHEMA:
        return False, ExecutionStep(tool="", args={}), f"Unknown tool: {tool_name}"
    
    schema = TOOL_VALIDATION_SCHEMA[tool_name]
    
    # Normalize arguments
    normalized_args = {}
    for raw_key, raw_value in args.items():
        # Apply alias mapping
        aliases = ARG_ALIASES.get(tool_name, {})
        normalized_key = aliases.get(raw_key.lower(), raw_key)
        
        # Check for unsupported expressions
        expr_error = _detect_unsupported_expressions(raw_value)
        if expr_error:
            return False, ExecutionStep(tool="", args={}), expr_error
        
        # Resolve variable references if they start with $
        resolved_value = raw_value
        if isinstance(raw_value, str) and raw_value.startswith("$"):
            resolved_value = _resolve_variable_reference(raw_value, prior_step_results)
            if resolved_value is None:
                return False, ExecutionStep(tool="", args={}), f"Invalid reference: {raw_value}"
        
        normalized_args[normalized_key] = resolved_value
    
    # Validate required fields are present
    missing_fields = []
    for required_field in schema["required"]:
        if required_field not in normalized_args:
            missing_fields.append(required_field)
    
    if missing_fields:
        return False, ExecutionStep(tool="", args={}), f"Missing required arguments: {', '.join(missing_fields)}"
    
    # Validate symbol names for insert_symbol
    if tool_name == "insert_symbol":
        block_name = normalized_args.get("block_name", "")
        if block_name and block_name not in available_symbols:
            # Try fuzzy matching
            similar = _find_similar_symbol(block_name, available_symbols)
            if similar:
                _log("VALIDATOR", f"Auto-correcting symbol {block_name} -> {similar}")
                normalized_args["block_name"] = similar
            else:
                return False, ExecutionStep(tool="", args={}), f"Unknown symbol: {block_name}. Available: {', '.join(available_symbols[:5])}..."
    
    # Validate numeric types
    for numeric_field in schema.get("type_hints", {}).keys():
        if numeric_field in normalized_args:
            value = normalized_args[numeric_field]
            # Allow deferred step references like $step2.x or $step3.y
            if isinstance(value, str) and value.startswith("$step"):
                continue
            if not isinstance(value, (int, float)):
                try:
                    normalized_args[numeric_field] = float(value)
                except (ValueError, TypeError):
                    return False, ExecutionStep(tool="", args={}), f"Invalid numeric value for {numeric_field}: {value}"
    
    # Remove unsupported arguments
    allowed_fields = set(schema["required"]) | set(schema["optional"])
    filtered_args = {k: v for k, v in normalized_args.items() if k in allowed_fields}
    
    # Log any removed arguments
    removed = set(normalized_args.keys()) - set(filtered_args.keys())
    if removed:
        _log("VALIDATOR", f"Removed unsupported arguments from {tool_name}: {', '.join(removed)}")
    
    normalized_step = ExecutionStep(tool=tool_name, args=filtered_args)
    return True, normalized_step, None


def _find_similar_symbol(name: str, available_symbols: List[str]) -> Optional[str]:
    """Find a similar symbol using fuzzy matching."""
    import difflib
    name_lower = name.lower()
    available_lower = [s.lower() for s in available_symbols]
    matches = difflib.get_close_matches(name_lower, available_lower, n=1, cutoff=0.65)
    if matches:
        idx = available_lower.index(matches[0])
        return available_symbols[idx]
    return None


def _resolve_variable_reference(reference: str, prior_step_results: Dict[str, Any]) -> Any:
    """
    Resolve variable references like $step1.entity_handle or $last_entity.
    
    Returns the resolved value or None if invalid.
    """
    if reference == "$last_entity":
        return prior_step_results.get("last_entity_handle")
    
    # Parse $stepN.property
    match = re.match(r'\$step(\d+)\.(\w+)', reference)
    if match:
        step_num = int(match.group(1))
        property_name = match.group(2)
        
        step_key = f"step{step_num}"
        if step_key in prior_step_results:
            step_result = prior_step_results[step_key]
            return step_result.get(property_name)
        
        return None
    
    # Direct step reference like $step1
    if reference.startswith("$step"):
        match = re.match(r'\$step(\d+)', reference)
        if match:
            step_num = int(match.group(1))
            step_key = f"step{step_num}"
            if step_key in prior_step_results:
                return prior_step_results[step_key].get("entity_handle")
    
    return None


def validate_plan(
    plan: ExecutionPlan,
    available_symbols: List[str]
) -> Tuple[bool, ExecutionPlan, List[str]]:
    """
    Validate and normalize a complete execution plan.
    
    Args:
        plan: ExecutionPlan from planner
        available_symbols: List of valid symbols in CAD
    
    Returns:
        (is_valid, normalized_plan, error_messages)
    """
    errors = []
    normalized_steps = []
    prior_step_results = {}
    
    for i, step in enumerate(plan.steps):
        is_valid, normalized_step, error = validate_and_normalize_step(
            step.dict(),
            available_symbols,
            prior_step_results
        )
        
        if not is_valid:
            errors.append(f"Step {i+1}: {error}")
            # Continue validation to collect all errors
        else:
            normalized_steps.append(normalized_step)
            # Store step result for reference using normalized arguments and expected output placeholders
            step_key = f"step{i+1}"
            step_result = {"tool": normalized_step.tool}
            step_result.update(normalized_step.args)
            if "entity_handle" not in step_result:
                step_result["entity_handle"] = f"${step_key}.entity_handle"
            if normalized_step.tool == "find_free_space_near_entity":
                step_result["x"] = f"${step_key}.x"
                step_result["y"] = f"${step_key}.y"
            prior_step_results[step_key] = step_result
    
    if errors:
        _log("VALIDATOR", f"Validation found {len(errors)} errors")
        return False, plan, errors
    
    # Create normalized plan
    normalized_plan = ExecutionPlan(
        thought=plan.thought,
        chat_only=plan.chat_only,
        steps=normalized_steps
    )
    
    _log("VALIDATOR", "Plan validation passed")
    return True, normalized_plan, []


def get_validation_error_feedback(errors: List[str]) -> str:
    """
    Generate validation error feedback for planner retry.
    
    This message is injected into the retry prompt to help the planner fix errors.
    """
    feedback = "Previous plan had validation errors:\n"
    for error in errors[:3]:  # Limit to first 3 errors
        feedback += f"- {error}\n"
    
    feedback += (
        "\nRules to follow:\n"
        "- Only use parameters defined in tool schemas\n"
        "- Use block_name for insert_symbol (not name or symbol)\n"
        "- Use entity_handle for all entity operations (not entity or id)\n"
        "- Use search_term for find_entity (not block_name or name)\n"
        "- Use start_handle and end_handle for connect_pipe (not entity1_id or entity2_id)\n"
        "- Never use arithmetic expressions like $step1.x + 100\n"
        "- Only use symbols from the available symbols list\n"
        "- Reference prior steps with $stepN.entity_handle, $stepN.handle, etc.\n"
    )
    
    return feedback
