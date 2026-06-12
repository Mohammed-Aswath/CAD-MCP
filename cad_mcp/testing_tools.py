"""Local MCP tool listing helper (stderr logging only; stdout-safe)."""

import asyncio
import logging

from cad_mcp.runtime.bridge import mcp

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    tools = asyncio.run(mcp.list_tools())
    logger.info("Registered tools: %s", tools)
