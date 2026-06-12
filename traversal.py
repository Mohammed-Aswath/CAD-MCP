from typing import List
from autocad_controller import AutoCADController
from schemas import EntityMetadata


def traverse_modelspace(controller: AutoCADController) -> List[EntityMetadata]:
    return [EntityMetadata(**controller.entity_metadata(entity)) for entity in controller.get_modelspace_entities()]
