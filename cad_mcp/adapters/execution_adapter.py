"""
Bridge MCP tool calls to the execution runtime.

Responsibilities:
    - standardized success/error envelopes
    - execution timing and logging
    - exception translation (no raw COM traces to clients)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, TypeVar

logger = logging.getLogger("cad_mcp.execution")

T = TypeVar("T")


def _format_exception(err: BaseException) -> str:
    """Human-readable message without leaking full stack to JSON by default."""
    return f"{type(err).__name__}: {err}"


def run_tool(
    tool_name: str,
    fn: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Invoke ``fn`` and return {success, result} or {success, error, tool}.

    Logs tool name, args (repr), duration, and outcome.
    """
    start = time.perf_counter()
    log_kwargs = {k: v for k, v in kwargs.items()}
    logger.info("MCP tool start tool=%s args=%s kwargs=%s", tool_name, args, log_kwargs)
    try:
        result = fn(*args, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        payload: Dict[str, Any] = {"success": True, "result": result}
        summary = (
            list(result.keys())
            if isinstance(result, dict)
            else type(result).__name__
        )
        logger.info(
            "MCP tool ok tool=%s duration_ms=%.2f result_summary=%s",
            tool_name,
            elapsed_ms,
            summary,
        )
        return payload
    except Exception as exc:  # noqa: BLE001 — boundary: translate all to JSON
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        logger.exception(
            "MCP tool fail tool=%s duration_ms=%.2f err=%s",
            tool_name,
            elapsed_ms,
            exc,
        )
        return {
            "success": False,
            "error": _format_exception(exc),
            "tool": tool_name,
        }
