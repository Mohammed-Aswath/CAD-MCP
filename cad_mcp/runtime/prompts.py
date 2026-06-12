"""Reusable MCP prompts for CAD workflows."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cad_mcp.prompts")


def register_prompts(mcp: Any) -> None:
    """Register lightweight reusable prompt templates."""

    @mcp.prompt()
    def pid_assistant_prompt() -> str:
        """General P&ID CAD assistant behavior."""
        return """
You are a CAD orchestration assistant for P&ID workflows.
- Use engineering terminology precisely (instrument, valve, line class, layer, handle).
- Prefer deterministic operations tied to logical handles (SYM_*, PIPE_*, CAD_*).
- Keep edits safe: validate target entities before proposing changes.
- For piping tasks, preserve orthogonal routing and endpoint connectivity.
- If data is incomplete, ask for missing handles, coordinates, or layer context.
""".strip()

    @mcp.prompt()
    def pipe_routing_prompt() -> str:
        """Orthogonal pipe routing guidance."""
        return """
Pipe routing guidance:
- Route pipes orthogonally (horizontal/vertical segments).
- Preserve start and end logical handles.
- Avoid ambiguous crossings when possible; maintain clear topology.
- Confirm layer conventions before placement.
- Report resulting pipe handle and connected endpoints.
""".strip()

    @mcp.prompt()
    def symbol_insertion_prompt() -> str:
        """Symbol insertion conventions."""
        return """
Symbol insertion conventions:
- Use canonical symbol names when possible; resolve aliases explicitly.
- Provide insertion coordinates in drawing units.
- Set rotation and layer intentionally; avoid implicit defaults when uncertain.
- Verify insertion by returning logical handle and normalized position metadata.
""".strip()

    @mcp.prompt()
    def drawing_analysis_prompt() -> str:
        """Guide analysis of CAD topology and metadata."""
        return """
Drawing analysis checklist:
- Inspect entities, pipes, and layer distribution first.
- Track connectivity via logical handles and pipe endpoints.
- Distinguish symbols from raw unmanaged CAD entities.
- Summarize counts, topology constraints, and missing metadata.
- Prefer read-only analysis before proposing modifications.
""".strip()

    logger.info(
        "Prompt registration success: pid_assistant_prompt, pipe_routing_prompt, "
        "symbol_insertion_prompt, drawing_analysis_prompt"
    )
