import logging

from cad_mcp.transport.stdio_transport import run_stdio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger("cad_mcp.launcher")

if __name__ == "__main__":
    logger.info("Starting CAD MCP Server via STDIO...")
    run_stdio()