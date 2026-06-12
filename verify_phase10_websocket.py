from pathlib import Path
from cad_mcp.transport.websocket_transport import MCPWebSocketTransport

output_path = Path("verification/phase10_websocket.txt")

with open(output_path, "w", encoding="utf-8") as f:
    f.write("=== WEBSOCKET TRANSPORT VERIFICATION ===\n\n")

    try:
        transport = MCPWebSocketTransport()

        f.write("WebSocket transport initialization: SUCCESS\n")
        f.write(f"Transport object: {transport}\n")

    except Exception as e:
        f.write("WebSocket verification FAILED\n")
        f.write(str(e))

print(f"Verification written to: {output_path}")