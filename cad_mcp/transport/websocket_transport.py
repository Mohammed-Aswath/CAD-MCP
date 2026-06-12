"""
WebSocket transport wrapper for MCP runtime.

This module keeps transport thin and reuses the shared FastMCP instance from
``cad_mcp.runtime.bridge``. If official websocket APIs are unavailable in the
installed SDK version, it exposes a clean async placeholder for future wiring.
"""

from __future__ import annotations

import inspect
import logging
import time
from typing import Any, Dict, Optional

from cad_mcp.runtime.bridge import mcp

logger = logging.getLogger("cad_mcp.transport.websocket")


class MCPWebSocketTransport:
    """Async lifecycle manager for websocket-compatible MCP serving."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._started = False
        self._mode = "uninitialized"
        self._server_handle: Optional[Any] = None

    async def start(self) -> Dict[str, Any]:
        """
        Start websocket transport if supported by SDK.

        Strategy:
        1. Prefer explicit websocket API if present.
        2. Fallback to generic async run signature with transport='websocket'.
        3. Otherwise return placeholder capability result.
        """
        t0 = time.perf_counter()
        logger.info(
            "websocket_transport_start host=%s port=%s",
            self.host,
            self.port,
        )
        if self._started:
            return {"success": True, "mode": self._mode, "already_started": True}
        try:
            # 1) Official/explicit method, if SDK exposes one.
            explicit = getattr(mcp, "run_websocket_async", None)
            if callable(explicit):
                self._server_handle = await explicit(host=self.host, port=self.port)
                self._mode = "official_websocket"
                self._started = True
                return self._ok(t0)

            # 2) Generic async run with transport keyword.
            generic = getattr(mcp, "run_async", None)
            if callable(generic):
                sig = inspect.signature(generic)
                kwargs: Dict[str, Any] = {}
                if "transport" in sig.parameters:
                    kwargs["transport"] = "websocket"
                if "host" in sig.parameters:
                    kwargs["host"] = self.host
                if "port" in sig.parameters:
                    kwargs["port"] = self.port
                if "transport" in kwargs:
                    self._server_handle = await generic(**kwargs)
                    self._mode = "generic_websocket"
                    self._started = True
                    return self._ok(t0)

            # 3) Placeholder path.
            self._mode = "placeholder"
            logger.warning(
                "websocket_transport_unavailable sdk_has_no_websocket_api "
                "host=%s port=%s",
                self.host,
                self.port,
            )
            return {
                "success": False,
                "mode": self._mode,
                "error": "WebSocket transport not available in installed MCP SDK",
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("websocket_transport_start_failed err=%s", exc)
            return {
                "success": False,
                "mode": self._mode,
                "error": f"{type(exc).__name__}: {exc}",
            }

    async def shutdown(self) -> Dict[str, Any]:
        """Shutdown websocket transport gracefully when backend provides hooks."""
        logger.info("websocket_transport_shutdown_start mode=%s", self._mode)
        try:
            if self._server_handle is not None:
                close = getattr(self._server_handle, "close", None)
                wait_closed = getattr(self._server_handle, "wait_closed", None)
                if callable(close):
                    close()
                if callable(wait_closed):
                    await wait_closed()
            self._started = False
            logger.info("websocket_transport_shutdown_complete mode=%s", self._mode)
            return {"success": True, "mode": self._mode}
        except Exception as exc:  # noqa: BLE001
            logger.exception("websocket_transport_shutdown_failed err=%s", exc)
            return {
                "success": False,
                "mode": self._mode,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _ok(self, t0: float) -> Dict[str, Any]:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        logger.info(
            "websocket_transport_start_ok mode=%s duration_ms=%.2f",
            self._mode,
            elapsed_ms,
        )
        return {
            "success": True,
            "mode": self._mode,
            "host": self.host,
            "port": self.port,
            "duration_ms": elapsed_ms,
        }
