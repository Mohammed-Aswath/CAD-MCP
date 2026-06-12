"""

FastMCP application singleton for CAD orchestration.



This module **must not** be named ``server.py``: a file ``mcp/server.py`` would

register as the import name ``mcp.server`` and shadow the official MCP SDK’s

``mcp.server`` package, breaking :mod:`mcp._sdk`.



Loads the official MCP SDK via :mod:`mcp._sdk`. Does **not** connect to AutoCAD

at import time.



Expose the shared ``mcp`` object for transports and tests.

"""



from __future__ import annotations



import logging
import sys

from cad_mcp._sdk import get_fastmcp_factory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    stream=sys.stderr,
    force=True,
)

logger = logging.getLogger("cad_mcp.runtime.bridge")



FastMCP = get_fastmcp_factory()

mcp = FastMCP("CAD-MCP-Server")



logger.info(

    "FastMCP server object ready (lazy AutoCAD connection; no COM at import).",

)



from .prompts import register_prompts  # noqa: E402
from .resources import register_resources  # noqa: E402
from .tools import register_tools  # noqa: E402



register_tools(mcp)
register_resources(mcp)
register_prompts(mcp)


