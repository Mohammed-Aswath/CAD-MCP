import logging
from typing import Any, Dict, List

from agent_memory import AgentMemory

logger = logging.getLogger(__name__)
from entity_manager import refresh_entities
from execution_models import ExecutionPlan
from tool_registry import TOOLS, execute_tool


def _log(category: str, message: str) -> None:
    logger.info("[%s] %s", category, message)


def _resolve_variables(value: Any, context: Dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        if value == "$last_entity":
            return context.get("memory").get_last_entity_handle()

        if value.startswith("$step"):
            path = value[1:].split(".")
            if not path:
                return value

            step_key = path[0]
            step_result = context.get("steps", {}).get(step_key, {})
            current = step_result
            for segment in path[1:]:
                if isinstance(current, dict):
                    current = current.get(segment)
                else:
                    current = None
                    break
            return current

        return value

    if isinstance(value, dict):
        return {k: _resolve_variables(v, context) for k, v in value.items()}

    if isinstance(value, list):
        return [_resolve_variables(item, context) for item in value]

    return value


class ExecutionEngine:
    def __init__(self, memory: AgentMemory):
        self.memory = memory
        self.step_results: Dict[str, Dict[str, Any]] = {}
        self.execution_log: List[Dict[str, Any]] = []

    def execute_plan(self, plan: ExecutionPlan) -> Dict[str, Any]:
        _log("EXECUTOR", f"Executing plan: {plan.thought}")
        self.step_results = {}
        self.execution_log = []
        errors: List[Dict[str, Any]] = []
        actions: List[Dict[str, Any]] = []

        context = {
            "memory": self.memory,
            "steps": self.step_results,
        }

        for idx, step in enumerate(plan.steps, start=1):
            step_key = f"step{idx}"
            _log("EXECUTOR", f"Running {step_key}: {step.tool}")

            resolved_args = {
                arg_name: _resolve_variables(arg_value, context)
                for arg_name, arg_value in step.args.items()
            }
            resolved_args = self._coerce_connect_pipe_args(step.tool, resolved_args, context)
            resolved_args = self._coerce_find_space_args(step.tool, resolved_args, context)

            tool_result = execute_tool(step.tool, resolved_args)
            self.step_results[step_key] = tool_result
            self.memory.record_tool_result(tool_result)

            action = {
                "step": step_key,
                "tool": step.tool,
                "args": resolved_args,
                "status": "success" if tool_result.get("success") else "failed",
                "result": tool_result,
            }
            actions.append(action)
            self.execution_log.append(action)

            # Sync AutoCAD modelspace after each step to keep subsequent steps in sync.
            try:
                refresh_entities()
                _log("CAD", f"Synced modelspace after {step_key}")
            except Exception as exc:
                _log("ERROR", f"Modelspace sync failed after {step_key}: {exc}")

            validation = self._validate_step(step.tool, tool_result)
            if not validation.get("success", False):
                errors.append({"step": step_key, "error": validation.get("error")})
                _log("VERIFY", f"Step {step_key} validation failed: {validation.get('error')}")
                break

            _log("VERIFY", f"Step {step_key} validated")

        return {
            "success": len(errors) == 0,
            "actions": actions,
            "step_results": self.step_results,
            "errors": errors,
            "execution_log": self.execution_log,
        }

    def _coerce_connect_pipe_args(
        self,
        tool_name: str,
        resolved_args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        if tool_name != "connect_pipe":
            return resolved_args

        def _first_match_handle(step_key: str) -> str | None:
            step_result = context.get("steps", {}).get(step_key, {})
            matches = step_result.get("matches")
            if isinstance(matches, list) and matches:
                first = matches[0]
                if isinstance(first, dict):
                    return first.get("handle")
            return None

        if resolved_args.get("start_handle") is None:
            resolved_args["start_handle"] = _first_match_handle("step1")
        if resolved_args.get("end_handle") is None:
            resolved_args["end_handle"] = _first_match_handle("step2")
        return resolved_args

    def _coerce_find_space_args(
        self,
        tool_name: str,
        resolved_args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        if tool_name != "find_free_space_near_entity":
            return resolved_args

        if resolved_args.get("reference_handle") is None:
            step1 = context.get("steps", {}).get("step1", {})
            matches = step1.get("matches")
            if isinstance(matches, list) and matches:
                first = matches[0]
                if isinstance(first, dict):
                    resolved_args["reference_handle"] = first.get("handle")
        return resolved_args

    def _validate_step(self, tool_name: str, result: Dict[str, Any]) -> Dict[str, Any]:
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "Tool failed")}

        if tool_name == "insert_symbol":
            if not result.get("entity_handle"):
                return {"success": False, "error": "Insert missing entity handle"}

        if tool_name == "move_entity":
            if not result.get("new_position"):
                return {"success": False, "error": "Move did not return updated position"}

        if tool_name == "rotate_entity":
            if result.get("new_rotation") is None:
                return {"success": False, "error": "Rotate did not return updated rotation"}

        if tool_name == "delete_entity":
            if not result.get("deleted_handle"):
                return {"success": False, "error": "Delete did not confirm deleted handle"}

        if tool_name == "connect_pipe":
            if not result.get("pipe_handle"):
                return {"success": False, "error": "Connect did not return pipe handle"}

        return {"success": True}
