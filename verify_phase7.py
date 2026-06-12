import asyncio
import json
from pathlib import Path

import entity_manager

from cad_mcp.bridge import mcp


async def main():

    output_path = Path("verification/phase7_runtime_test.txt")

    with open(output_path, "w", encoding="utf-8") as f:

        f.write("=== PHASE 7 RUNTIME TEMPLATE VERIFICATION ===\n\n")

        try:

            # Pull REAL entities
            entities = entity_manager.get_entities()

            f.write(f"REAL ENTITY COUNT: {len(entities)}\n\n")

            if not entities:
                f.write("NO ENTITIES FOUND IN DRAWING\n")
                f.write("Insert at least one symbol before testing.\n")
                return

            # Use first real entity
            first_entity = entities[0]

            handle = first_entity.handle

            f.write(f"TEST HANDLE: {handle}\n\n")

            # Construct dynamic URI
            uri = f"cad://entity/{handle}"

            f.write(f"TEST URI: {uri}\n\n")

            # REAL MCP TEMPLATE RESOLUTION TEST
            result = await mcp.read_resource(uri)

            f.write("RESOURCE RESOLUTION: SUCCESS\n\n")

            f.write(str(result))

            # Optional JSON safety check
            try:
                json.dumps(str(result))
                f.write("\n\nJSON SERIALIZATION: SUCCESS\n")

            except Exception as serialization_error:
                f.write("\n\nJSON SERIALIZATION FAILED:\n")
                f.write(str(serialization_error))

        except Exception as e:

            f.write("RUNTIME TEMPLATE TEST FAILED\n\n")

            f.write(str(e))

    print(f"Verification written to: {output_path}")


asyncio.run(main())