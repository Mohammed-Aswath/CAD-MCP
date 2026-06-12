from pathlib import Path

from cad_mcp.runtime.discovery import (
    get_tool_manifest,
    get_resource_manifest,
    get_prompt_manifest,
    get_server_manifest,
)

output_path = Path("verification/phase11_discovery.txt")

with open(output_path, "w", encoding="utf-8") as f:
    f.write("=== MCP DISCOVERY VERIFICATION ===\n\n")


    try:
        tools = get_tool_manifest()
        resources = get_resource_manifest()
        prompts = get_prompt_manifest()
        server = get_server_manifest()

        f.write("TOOLS:\n")
        f.write(str(tools))
        f.write("\n\n")

        f.write("RESOURCES:\n")
        f.write(str(resources))
        f.write("\n\n")

        f.write("PROMPTS:\n")
        f.write(str(prompts))
        f.write("\n\n")

        f.write("SERVER:\n")
        f.write(str(server))
        f.write("\n\n")

        f.write("DISCOVERY STATUS: SUCCESS\n")

    except Exception as e:
        f.write("DISCOVERY STATUS: FAILED\n")
        f.write(str(e))

print(f"Verification written to: {output_path}")