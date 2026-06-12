import asyncio
from pathlib import Path

from cad_mcp.bridge import mcp


async def main():
    output_path = Path("verification/phase8_prompts.txt")

    prompts = await mcp.list_prompts()

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("=== MCP PROMPT VERIFICATION ===\n\n")

        f.write(f"Total Prompts: {len(prompts)}\n\n")

        for prompt in prompts:
            f.write(str(prompt))
            f.write("\n\n")

    print(f"Verification written to: {output_path}")


asyncio.run(main())