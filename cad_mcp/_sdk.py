"""
Load ``FastMCP`` from the **installed** PyPI ``mcp`` package.

This repository also contains a top-level package directory named ``mcp/``, so
``import mcp`` resolves to our adapter. The official SDK must be reached by
temporarily replacing ``sys.modules['mcp']`` with a stub whose ``__path__`` is
``site-packages/mcp``, then importing ``mcp.server.fastmcp.server`` (the module
that defines ``FastMCP``) without relying on ``from mcp.server.fastmcp import``
which can execute ``mcp/__init__.py`` and pull optional client dependencies.
"""

from __future__ import annotations

import importlib
import sys
import sysconfig
import types
from pathlib import Path
from typing import Any, Callable, Type

_FASTMCP_CLS: Type[Any] | None = None


def load_fastmcp_class() -> Type[Any]:
    """
    Return the ``FastMCP`` class from the installed MCP Python SDK.

    Raises
    ------
    ImportError
        If the SDK is not installed or ``FastMCP`` cannot be found.
    """
    global _FASTMCP_CLS
    if _FASTMCP_CLS is not None:
        return _FASTMCP_CLS

    pure = Path(sysconfig.get_paths()["purelib"])
    pypi_mcp_root = pure / "mcp"
    if not pypi_mcp_root.is_dir():
        raise ImportError(
            "The 'mcp' package is not installed in site-packages. "
            "Install with: pip install mcp",
        )

    saved_mcp = sys.modules.get("mcp")
    stub = types.ModuleType("mcp")
    stub.__path__ = [str(pypi_mcp_root)]
    sys.modules["mcp"] = stub
    try:
        mod = importlib.import_module("mcp.server.fastmcp.server")
        cls = getattr(mod, "FastMCP", None)
        if cls is None:
            raise ImportError("FastMCP class not found in mcp.server.fastmcp.server")
        _FASTMCP_CLS = cls
        return cls
    finally:
        if saved_mcp is not None:
            sys.modules["mcp"] = saved_mcp
        else:
            sys.modules.pop("mcp", None)


def get_fastmcp_factory() -> Callable[..., Any]:
    """Return the FastMCP constructor (class)."""
    return load_fastmcp_class()
