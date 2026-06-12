import asyncio
from pathlib import Path

from cad_mcp.bridge import mcp


async def main():
    output_path = Path("verification/final_mcp_status.txt")

    tools = await mcp.list_tools()
    resources = await mcp.list_resources()
    prompts = await mcp.list_prompts()

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("=== FINAL MCP STATUS ===\n\n")

        f.write("TOOLS:\n")
        f.write(str(tools))
        f.write("\n\n")

        f.write("RESOURCES:\n")
        f.write(str(resources))
        f.write("\n\n")

        f.write("PROMPTS:\n")
        f.write(str(prompts))
        f.write("\n\n")

    print(f"Verification written to: {output_path}")


asyncio.run(main())