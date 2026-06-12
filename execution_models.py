from pydantic import BaseModel
from typing import Any, Dict, List


class ExecutionStep(BaseModel):
    tool: str
    args: Dict[str, Any] = {}


class ExecutionPlan(BaseModel):
    thought: str
    steps: List[ExecutionStep] = []
    chat_only: bool = False
