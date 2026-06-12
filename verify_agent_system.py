from agent_engine import AIAgent
from agent_memory import AgentMemory
from execution_models import ExecutionPlan, ExecutionStep
from execution_engine import ExecutionEngine


def test_memory():
    memory = AgentMemory()
    memory.add_conversation("user", "Hello")
    memory.record_tool_result({"success": True, "entity_handle": "A1", "message": "Test entity"})
    assert memory.get_last_entity_handle() == "A1"
    print("[VERIFY] Memory test passed")


def test_execution_engine():
    memory = AgentMemory()
    engine = ExecutionEngine(memory)
    plan = ExecutionPlan(
        thought="Test empty plan execution",
        steps=[],
    )
    result = engine.execute_plan(plan)
    assert isinstance(result, dict)
    assert result.get("success") is True
    print("[VERIFY] Execution engine empty-plan test passed")


def test_agent_import():
    agent = AIAgent()
    assert hasattr(agent, "process_message")
    print("[VERIFY] Agent import test passed")


if __name__ == "__main__":
    print("Running agent system verification")
    test_memory()
    test_agent_import()
    test_execution_engine()
    print("[VERIFY] Agent system verification completed")
