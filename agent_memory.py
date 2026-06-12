import logging
from typing import Any, Dict, List, Optional

from symbol_aliases import SYMBOL_ALIASES, resolve_symbol_name

logger = logging.getLogger(__name__)


def _log(category: str, message: str) -> None:
    logger.info("[%s] %s", category, message)


class AgentMemory:
    def __init__(self):
        self.recent_entities: List[Dict[str, Any]] = []
        self.selected_entities: List[Dict[str, Any]] = []
        self.last_tool_results: List[Dict[str, Any]] = []
        self.conversation_history: List[Dict[str, Any]] = []
        self.plan_history: List[Dict[str, Any]] = []

    def add_conversation(self, role: str, message: str) -> None:
        self.conversation_history.append({"role": role, "message": message})
        _log("MEMORY", f"Stored conversation entry: {role}")

    def record_tool_result(self, tool_result: Dict[str, Any]) -> None:
        self.last_tool_results.append(tool_result)
        self._remember_entities(tool_result)
        _log("MEMORY", f"Recorded tool result: {tool_result.get('message', 'no message')}")

    def _remember_entities(self, tool_result: Dict[str, Any]) -> None:
        entity_handle = tool_result.get("entity_handle")
        deleted_handle = tool_result.get("deleted_handle")
        pipe_handle = tool_result.get("pipe_handle")

        if entity_handle:
            self.recent_entities.insert(0, {
                "handle": entity_handle,
                "block_name": tool_result.get("entity", {}).get("block_name"),
            })

        if deleted_handle:
            self.recent_entities = [ent for ent in self.recent_entities if ent.get("handle") != deleted_handle]

        if pipe_handle:
            self.recent_entities.insert(0, {"handle": pipe_handle, "block_name": "pipe"})

        self.recent_entities = self.recent_entities[:10]

    def get_last_entity_handle(self) -> Optional[str]:
        if self.recent_entities:
            return self.recent_entities[0].get("handle")
        return None

    def resolve_symbol_alias(self, name: str, available_symbols: List[str]) -> str:
        return resolve_symbol_name(name, available_symbols)

    def resolve_entity_reference(self, reference: str) -> Optional[str]:
        lower_ref = reference.lower().strip()
        if lower_ref in ["last", "last_entity", "it", "them"]:
            return self.get_last_entity_handle()
        if lower_ref.startswith("step"):
            return lower_ref

        # Resolve last inserted entity by type
        if lower_ref in SYMBOL_ALIASES:
            alias = SYMBOL_ALIASES[lower_ref]
            for ent in self.recent_entities:
                if ent.get("block_name") and ent.get("block_name").lower() == alias.lower():
                    return ent.get("handle")

        return None

    def add_plan_history(self, plan: Dict[str, Any], execution_context: Dict[str, Any]) -> None:
        self.plan_history.append({"plan": plan, "execution": execution_context})
        _log("MEMORY", "Added execution plan history")
