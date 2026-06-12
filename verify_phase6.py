import asyncio
from pathlib import Path

from cad_mcp.bridge import mcp


async def main():
    output_path = Path("verification/phase6_resources.txt")

    resources = await mcp.list_resources()

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("=== MCP RESOURCE VERIFICATION ===\n\n")

        f.write(f"Total Resources: {len(resources)}\n\n")

        for resource in resources:
            f.write(str(resource))
            f.write("\n\n")

    print(f"Verification written to: {output_path}")


asyncio.run(main())