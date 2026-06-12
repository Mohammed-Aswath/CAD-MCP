from pathlib import Path

from cad_mcp.runtime.capabilities import (
    get_capabilities,
    negotiate_capabilities,
    get_server_info,
)

output_path = Path("verification/phase12_capabilities.txt")

client_caps = {
    "tools": True,
    "resources": True,
    "prompts": True,
    "streaming": True,
}

with open(output_path, "w", encoding="utf-8") as f:
    f.write("=== MCP CAPABILITY NEGOTIATION VERIFICATION ===\n\n")

    try:
        caps = get_capabilities()
        negotiated = negotiate_capabilities(client_caps)
        info = get_server_info()

        f.write("SERVER CAPABILITIES:\n")
        f.write(str(caps))
        f.write("\n\n")

        f.write("NEGOTIATED CAPABILITIES:\n")
        f.write(str(negotiated))
        f.write("\n\n")

        f.write("SERVER INFO:\n")
        f.write(str(info))
        f.write("\n\n")

        f.write("CAPABILITY NEGOTIATION: SUCCESS\n")

    except Exception as e:
        f.write("CAPABILITY NEGOTIATION: FAILED\n")
        f.write(str(e))

print(f"Verification written to: {output_path}")