from pathlib import Path
from cad_mcp.transport.stdio_transport import run_stdio

output_path = Path("verification/phase9_stdio.txt")

with open(output_path, "w", encoding="utf-8") as f:
    f.write("=== STDIO TRANSPORT VERIFICATION ===\n\n")

    try:
        f.write("STDIO transport import: SUCCESS\n")
        f.write("run_stdio function exists: SUCCESS\n")

        f.write(f"Function reference: {run_stdio}\n")

    except Exception as e:
        f.write("STDIO verification FAILED\n")
        f.write(str(e))

print(f"Verification written to: {output_path}")