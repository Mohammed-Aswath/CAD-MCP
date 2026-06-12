import json
from pathlib import Path

import entity_manager

from cad_mcp.adapters.entity_adapter import serialize_entities

output_path = Path("verification/serialization_checks.txt")

with open(output_path, "w", encoding="utf-8") as f:

    f.write("=== REAL ENTITY SERIALIZATION VERIFICATION ===\n\n")

    try:

        # Pull REAL runtime entities
        entities = entity_manager.get_entities()

        f.write(f"REAL ENTITY COUNT: {len(entities)}\n\n")

        # Convert Pydantic objects into serializable structures
        raw_entities = []

        for entity in entities:

            if hasattr(entity, "model_dump"):
                raw_entities.append(entity.model_dump())

            elif hasattr(entity, "dict"):
                raw_entities.append(entity.dict())

            else:
                raw_entities.append(vars(entity))

        # Run through MCP serialization adapter
        serialized = serialize_entities(raw_entities)

        # CRITICAL VALIDATION
        json.dumps(serialized)

        f.write("JSON SERIALIZATION: SUCCESS\n\n")

        f.write(json.dumps(serialized, indent=2))

    except Exception as e:

        f.write("JSON SERIALIZATION: FAILED\n\n")

        f.write(str(e))

print(f"Verification written to: {output_path}")