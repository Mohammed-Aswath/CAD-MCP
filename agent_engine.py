from typing import Any, Dict, List
import json
import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Try to import the new Gemini SDK first, fall back to legacy
GENAI_NEW = False
genai = None
GENAI_AVAILABLE = False

try:
    import google.genai as genai
    GENAI_AVAILABLE = True
    GENAI_NEW = True
except Exception as e:
    logger.warning("[IMPORT] google.genai not available (%s)", type(e).__name__)
    try:
        import google.generativeai as genai
        GENAI_AVAILABLE = True
        GENAI_NEW = False
    except Exception as e2:
        logger.warning("[IMPORT] google.generativeai also failed: %s", type(e2).__name__)
        genai = None
        GENAI_AVAILABLE = False
        GENAI_NEW = False

from agent_context import get_cad_context, build_context_summary
from agent_memory import AgentMemory
from execution_engine import ExecutionEngine
from execution_models import ExecutionPlan, ExecutionStep
from symbol_aliases import SYMBOL_ALIASES
from tool_registry import TOOL_SCHEMAS
from entity_manager import get_available_symbols
from plan_validator import validate_plan, get_validation_error_feedback

load_dotenv()

GEMINI_MODEL_NAME = "gemini-flash-latest"


def _log(category: str, message: str) -> None:
    logger.info("[%s] %s", category, message)


class AIAgent:
    def __init__(self):
        self.memory = AgentMemory()
        self.execution_engine = ExecutionEngine(self.memory)
        self.api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        self.gemini_enabled = bool(self.api_key and GENAI_AVAILABLE)
        self.validation_retry_count = {}  # Track retry attempts per message
        self.last_planner_error: str | None = None

        if self.gemini_enabled:
            if GENAI_NEW:
                self.client = genai.Client(api_key=self.api_key)
                self.model = None
                self._log("AGENT", f"Gemini planner enabled ({GEMINI_MODEL_NAME}) using google.genai")
            else:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel(model_name=GEMINI_MODEL_NAME)
                self.client = None
                self._log("AGENT", f"Gemini planner enabled ({GEMINI_MODEL_NAME}) using google.generativeai")
        else:
            self.model = None
            self.client = None
            if self.api_key and not GENAI_AVAILABLE:
                self._log("AGENT", "Gemini API key present but supported Gemini SDK package is missing")
            else:
                self._log("AGENT", "Gemini disabled; using fallback planner")

        self._log("AGENT", "AIAgent initialized")

    def _log(self, category: str, message: str) -> None:
        _log(category, message)

    def process_message(self, user_message: str) -> Dict[str, Any]:
        self.memory.add_conversation("user", user_message)
        self.last_planner_error = None
        context_summary = build_context_summary()

        plan = self._construct_execution_plan(user_message, context_summary)
        self._log("PLANNER", f"Execution plan built: {plan.dict()}")

        # Validate and normalize plan if it has steps
        if plan.steps and not plan.chat_only:
            available_symbols = get_available_symbols()
            is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)
            
            if not is_valid:
                self._log("VALIDATOR", f"Plan validation failed with {len(errors)} errors")
                
                # Try one retry with validation feedback
                msg_id = id(user_message)
                retry_count = self.validation_retry_count.get(msg_id, 0)
                
                if retry_count < 1 and self.gemini_enabled:
                    self._log("VALIDATOR", "Attempting plan regeneration with validation feedback")
                    self.validation_retry_count[msg_id] = retry_count + 1
                    
                    feedback = get_validation_error_feedback(errors)
                    plan = self._generate_plan_with_gemini(user_message, context_summary, feedback)
                    
                    # Re-validate after retry
                    is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)
                
                # If still invalid, fall back to chat-only
                if not is_valid:
                    self._log("VALIDATOR", "Validation still failed after retry; falling back to chat-only")
                    plan = ExecutionPlan(thought="Plan validation failed", chat_only=True, steps=[])
                    normalized_plan = plan
            else:
                plan = normalized_plan

        if plan.chat_only or not plan.steps:
            response_text = self._synthesize_chat_response(user_message, plan, context_summary)
            self.memory.add_conversation("assistant", response_text)
            failed_plan = plan.chat_only and not plan.steps and bool(self.last_planner_error)
            return {
                "success": not failed_plan,
                "response": response_text,
                "thought": plan.thought,
                "steps": [step.dict() for step in plan.steps],
                "execution_results": [],
                "summary": response_text,
                "actions": [],
                "tool_results": [],
                "context": context_summary,
            }

        execution_context = self.execution_engine.execute_plan(plan)
        success = execution_context["success"]
        actions = execution_context["actions"]
        tool_results = [action["result"] for action in actions]
        self.memory.add_plan_history(plan.dict(), execution_context)

        response_text = self._synthesize_execution_response(plan, execution_context, context_summary)
        self.memory.add_conversation("assistant", response_text)

        return {
            "success": success,
            "response": response_text,
            "thought": plan.thought,
            "steps": [step.dict() for step in plan.steps],
            "execution_results": execution_context.get("execution_log", []),
            "summary": response_text,
            "actions": actions,
            "tool_results": tool_results,
            "context": context_summary,
        }

    def _construct_execution_plan(self, user_message: str, context_summary: str) -> ExecutionPlan:
        if self.gemini_enabled and self.model:
            return self._generate_plan_with_gemini(user_message, context_summary)
        return self._fallback_plan(user_message, context_summary)

    def _generate_plan_with_gemini(
        self, 
        user_message: str, 
        context_summary: str,
        validation_feedback: str = ""
    ) -> ExecutionPlan:
        self._log("PLANNER", "Generating execution plan with Gemini")
        prompt = self._build_planner_prompt(user_message, context_summary, validation_feedback)

        try:
            if GENAI_NEW and self.client is not None:
                chat = self.client.chats.create(model=GEMINI_MODEL_NAME)
                response = chat.send_message(
                    prompt,
                    config={
                        "temperature": 0,
                        "max_output_tokens": 2048,
                    }
                )
            else:
                response = self.model.generate_content(
                    prompt,
                    generation_config={
                        "temperature": 0,
                        "max_output_tokens": 2048,
                    }
                )
            raw_text = response.text.strip()
            self._log("PLANNER", f"Gemini output: {raw_text}")
            payload = self._extract_json_payload(raw_text)
            return ExecutionPlan.parse_obj(payload)
        except Exception as exc:
            self.last_planner_error = str(exc)
            self._log("ERROR", f"Gemini planning failed: {exc}")
            return ExecutionPlan(thought="Gemini unavailable or ambiguous request", chat_only=True, steps=[])

    def _build_planner_prompt(
        self, 
        user_message: str, 
        context_summary: str,
        validation_feedback: str = ""
    ) -> str:
        """
        Build the planner prompt with dynamically injected tool schemas and symbols.
        """
        # Get available symbols
        try:
            available_symbols = get_available_symbols()
        except Exception:
            available_symbols = ["pump", "motor", "4_way_valve", "3_way_valve"]
        
        # Build dynamic tool descriptions from schemas
        tool_descriptions = self._build_tool_descriptions()
        
        prompt_parts = [
            "You are an autonomous engineering CAD planner for an AutoCAD P&ID system.",
            "Your output must be valid JSON only. Do not include any explanation outside the JSON object.",
            "The JSON object must include these fields: thought, chat_only, steps.",
            "Each step must include 'tool' and 'args'.",
            "",
            "CRITICAL RULES:",
            "1. Arguments MUST exactly match the parameter names in the tool schema.",
            "2. Never invent parameter names.",
            "3. Do not use aliases like 'name', 'position', or 'id' unless explicitly defined.",
            "4. Only use symbols from the 'Available CAD Symbols' list.",
            "5. Never use arithmetic expressions like '$step1.x + 100'.",
            "6. Use find_free_space_near_entity for relative placement.",
            "7. Use $stepN.entity_handle to reference prior step results.",
            "8. Never use arrays like [x,y] for coordinates; use individual x, y fields.",
            "9. Never use unsupported filters or unsupported expressions.",
            "10. If unsure, set chat_only to true.",
            "",
            "AVAILABLE TOOLS WITH SCHEMAS:",
            "=" * 60,
            tool_descriptions,
            "=" * 60,
            "",
            "AVAILABLE CAD SYMBOLS (ONLY use these):",
            ", ".join(available_symbols),
            "",
        ]
        
        # Add validation feedback if retrying
        if validation_feedback:
            prompt_parts.extend([
                "VALIDATION FEEDBACK FROM PREVIOUS ATTEMPT:",
                "-" * 60,
                validation_feedback,
                "-" * 60,
                "",
            ])
        
        prompt_parts.extend([
            f"Context summary: {context_summary}",
            f"User request: {user_message}",
            "",
            "Return a JSON object with a natural thought phrase and the required execution steps.",
            "Example for 'add a pump':",
            '{"thought":"User wants to insert a pump symbol","chat_only":false,"steps":[{"tool":"insert_symbol","args":{"block_name":"pump","x":0,"y":0}}]}',
            "",
            "Example for 'connect two entities':",
            '{"thought":"Connect entities with pipe","chat_only":false,"steps":[{"tool":"connect_pipe","args":{"start_handle":"$step1.entity_handle","end_handle":"$step2.entity_handle"}}]}',
        ])
        
        return "\n".join(prompt_parts)

    def _build_tool_descriptions(self) -> str:
        """
        Build dynamic tool descriptions from TOOL_SCHEMAS.
        
        Returns a formatted string with all tool schemas.
        """
        descriptions = []
        
        for schema in TOOL_SCHEMAS:
            tool_name = schema.get("name", "unknown")
            description = schema.get("description", "No description")
            parameters = schema.get("parameters", {})
            properties = parameters.get("properties", {})
            required = parameters.get("required", [])
            
            desc_parts = [
                f"\nTool: {tool_name}",
                f"Description: {description}",
            ]
            
            if required:
                desc_parts.append("Required Parameters:")
                for param in required:
                    prop = properties.get(param, {})
                    prop_desc = prop.get("description", "")
                    desc_parts.append(f"  - {param}: {prop_desc}")
            
            optional_params = [p for p in properties.keys() if p not in required]
            if optional_params:
                desc_parts.append("Optional Parameters:")
                for param in optional_params:
                    prop = properties.get(param, {})
                    prop_desc = prop.get("description", "")
                    desc_parts.append(f"  - {param}: {prop_desc}")
            
            # Add example
            if tool_name == "insert_symbol":
                desc_parts.append('Example: {"tool":"insert_symbol","args":{"block_name":"pump","x":100,"y":100}}')
            elif tool_name == "move_entity":
                desc_parts.append('Example: {"tool":"move_entity","args":{"entity_handle":"$step1.entity_handle","dx":100,"dy":50}}')
            elif tool_name == "connect_pipe":
                desc_parts.append('Example: {"tool":"connect_pipe","args":{"start_handle":"$step1.entity_handle","end_handle":"$step2.entity_handle"}}')
            
            descriptions.append("\n".join(desc_parts))
        
        return "\n".join(descriptions)

    def _extract_json_payload(self, raw_text: str) -> Dict[str, Any]:
        try:
            start = raw_text.index("{")
            end = raw_text.rfind("}")
            if start != -1 and end != -1:
                payload_text = raw_text[start:end + 1]
                return json.loads(payload_text)
        except Exception as exc:
            self._log("ERROR", f"JSON extraction failed: {exc}")
        return {"thought": "Unable to plan", "chat_only": True, "steps": []}

    def _fallback_plan(self, user_message: str, context_summary: str) -> ExecutionPlan:
        self._log("PLANNER", "Constructing fallback plan")
        message = user_message.lower()

        greetings = ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"]
        if any(greeting in message for greeting in greetings):
            return ExecutionPlan(thought="Greeting received", chat_only=True, steps=[])

        if "symbols available" in message or "what symbols" in message or "available symbols" in message:
            return ExecutionPlan(
                thought="User requested available symbols",
                chat_only=True,
                steps=[],
            )

        if "how many" in message or "count" in message:
            return ExecutionPlan(
                thought="Count entities requested",
                chat_only=False,
                steps=[ExecutionStep(tool="count_entities", args={})],
            )

        return ExecutionPlan(thought="Gemini unavailable or ambiguous request", chat_only=True, steps=[])

    def _synthesize_chat_response(self, user_message: str, plan: ExecutionPlan, context_summary: str) -> str:
        if self.gemini_enabled and (self.model or self.client):
            try:
                prompt = (
                    "You are a helpful AutoCAD CAD assistant. Respond conversationally to the user request. "
                    "Do not suggest tools or restate JSON. "
                    f"Context summary: {context_summary}\n"
                    f"User request: {user_message}\n"
                )
                if GENAI_NEW and self.client is not None:
                    chat = self.client.chats.create(model=GEMINI_MODEL_NAME)
                    response = chat.send_message(
                        prompt,
                        config={
                            "temperature": 0,
                            "max_output_tokens": 2048,
                        }
                    )
                else:
                    response = self.model.generate_content(
                        prompt,
                        generation_config={
                            "temperature": 0,
                            "max_output_tokens": 2048,
                        }
                    )
                return response.text.strip()
            except Exception as exc:
                self.last_planner_error = str(exc)
                self._log("ERROR", f"Gemini chat response failed: {exc}")

        if self.last_planner_error and plan.chat_only and not plan.steps:
            return f"Unable to plan: {self.last_planner_error}. Please check Gemini quota and billing." 

        if any(greeting in user_message.lower() for greeting in ["hello", "hi", "hey"]):
            return "Hello! I am connected to the CAD environment and ready to assist. What would you like to do next?"

        if "symbols available" in user_message.lower() or "what symbols" in user_message.lower():
            return "You can insert pumps, motors, valves, gauges, sensors, tanks, vessels, and other P&ID symbols."

        return "I am ready to help with your CAD task. Please provide a command like 'Add a pump' or 'Connect the valve to the motor'."

    def _synthesize_execution_response(
        self,
        plan: ExecutionPlan,
        execution_context: Dict[str, Any],
        context_summary: str,
    ) -> str:
        if execution_context.get("success"):
            completed_steps = [action["tool"] for action in execution_context.get("actions", [])]
            return f"Executed plan successfully: {', '.join(completed_steps)}."

        errors = execution_context.get("errors", [])
        if errors:
            return f"Execution stopped due to error: {errors[0].get('error')}"

        return "Execution completed with partial results."
