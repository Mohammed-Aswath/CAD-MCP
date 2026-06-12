"""
STDIO transport entrypoint for external MCP clients.

Uses the shared FastMCP app from ``cad_mcp.runtime.bridge`` and keeps startup
lazy: no AutoCAD connection is performed until a tool/resource is called.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from types import FrameType
from typing import Any

from cad_mcp.runtime.bridge import mcp

logger = logging.getLogger("cad_mcp.transport.stdio")

_SHUTTING_DOWN = False


def _signal_handler(signum: int, _frame: FrameType | None) -> None:
    global _SHUTTING_DOWN

    _SHUTTING_DOWN = True

    logger.info(
        "STDIO transport shutdown signal received signum=%s",
        signum,
    )


def _bind_lifecycle_signals() -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)

            logger.debug(
                "Bound lifecycle signal handler sig=%s",
                sig,
            )

        except Exception:
            logger.debug(
                "Signal binding unavailable sig=%s",
                sig,
            )


async def _run_via_official_stdio_async(app: Any) -> bool:
    """
    Run FastMCP server using official MCP stdio transport.

    Keeps the process alive for external MCP clients
    such as Cursor, Claude Desktop, and Windsurf.

    Returns:
        bool: True if stdio runtime started successfully.
    """

    try:
        from mcp.server.stdio import stdio_server

    except Exception:
        logger.warning(
            "Official MCP stdio helper unavailable"
        )

        return False

    logger.info(
        "STDIO transport binding with official MCP stdio_server"
    )

    try:
        async with stdio_server() as (read_stream, write_stream):

            logger.info(
                "STDIO transport connected to read/write streams"
            )

            logger.info(
                "Starting persistent MCP protocol runtime loop"
            )

            await app._mcp_server.run(
                read_stream,
                write_stream,
                app._mcp_server.create_initialization_options(),
            )

            logger.info(
                "MCP protocol runtime loop exited cleanly"
            )

        return True

    except Exception as exc:
        logger.exception(
            "STDIO runtime failure error=%s",
            exc,
        )

        raise


async def _run_stdio_async() -> None:
    """
    Async STDIO runtime wrapper.
    """

    _bind_lifecycle_signals()

    logger.info(
        "STDIO transport startup"
    )

    logger.info(
        "STDIO transport bound to shared FastMCP instance"
    )

    logger.info(
        "FastMCP server name=%s",
        getattr(mcp, "name", "unknown"),
    )

    try:
        started = await _run_via_official_stdio_async(mcp)

        if started:
            logger.info(
                "STDIO runtime completed using official MCP transport"
            )

            return

        logger.info(
            "Official stdio helper unavailable; attempting FastMCP.run() fallback"
        )

        run = getattr(mcp, "run", None)

        if callable(run):

            logger.info(
                "Invoking FastMCP.run() fallback runtime"
            )

            maybe_awaitable = run()

            if asyncio.iscoroutine(maybe_awaitable):
                await maybe_awaitable

            logger.info(
                "FastMCP.run() fallback runtime exited cleanly"
            )

            return

        raise RuntimeError(
            "No usable stdio launcher found on FastMCP instance"
        )

    except Exception as exc:
        logger.exception(
            "STDIO transport fatal error=%s",
            exc,
        )

        raise

    finally:
        logger.info(
            "STDIO transport shutdown clean=%s",
            _SHUTTING_DOWN,
        )


def run_stdio() -> None:
    """
    Launch MCP server over STDIO transport for:

    - Cursor
    - Claude Desktop
    - Windsurf
    - Generic MCP clients
    """

    # IMPORTANT:
    # MCP STDIO protocol MUST NOT write protocol traffic to stdout.
    # Logs are redirected to stderr intentionally.

    root_logger = logging.getLogger()

    if not root_logger.handlers:

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
            handlers=[
                logging.StreamHandler(sys.stderr)
            ],
        )

    asyncio.run(_run_stdio_async())


if __name__ == "__main__":
    run_stdio()