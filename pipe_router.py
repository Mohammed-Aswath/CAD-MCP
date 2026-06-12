import logging
from typing import List, Tuple

from autocad_controller import AutoCADController

logger = logging.getLogger(__name__)

PIPE_LAYER = "PIPES"


def _make_orthogonal_route(start: Tuple[float, float, float], end: Tuple[float, float, float]) -> List[Tuple[float, float, float]]:
    sx, sy, sz = start
    ex, ey, ez = end
    if sx == ex or sy == ey:
        return [(sx, sy, sz), (ex, ey, ez)]
    mid_x = sx
    mid_y = ey
    return [(sx, sy, sz), (mid_x, mid_y, sz), (ex, ey, ez)]


def route_orthogonal_pipe(
    controller: AutoCADController,
    start_handle: str,
    end_handle: str
) -> str:
    logger.info("[PIPE] PIPE ROUTING START")
    if not controller.is_connected():
        raise RuntimeError("AutoCAD is not connected")

    controller.sync_modelspace_entities()

    start_handle = controller.resolve_logical_handle(start_handle)
    end_handle = controller.resolve_logical_handle(end_handle)
    if start_handle == end_handle:
        raise ValueError("Start and end handles are identical; select two different instruments")
    logger.info("[PIPE] Finding source entity: %s", start_handle)
    source = controller.get_entity_by_handle(start_handle)

    logger.info("[PIPE] Finding target entity: %s", end_handle)
    target = controller.get_entity_by_handle(end_handle)

    start = controller.connection_point_for(source)
    end = controller.connection_point_for(target)

    logger.info("[PIPE] Start point: %s", start)
    logger.info("[PIPE] End point: %s", end)

    if start == end:
        raise ValueError("Selected entities share the same center point; move one instrument and retry")

    points = _make_orthogonal_route(start, end)
    logger.info("[PIPE] Generated route: %s", points)

    if len(points) < 2:
        raise ValueError("Could not compute a pipe route")

    pipe_handle = controller.create_pipe(start_handle, end_handle, points, layer=PIPE_LAYER)
    logger.info("[PIPE] PIPE ROUTING COMPLETE: %s", pipe_handle)
    return pipe_handle
