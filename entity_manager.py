import json
import logging
import time
from pathlib import Path
from threading import RLock
from typing import Dict, List, Optional, Tuple

from autocad_controller import AutoCADController
from pipe_router import route_orthogonal_pipe
logger = logging.getLogger(__name__)

from schemas import (
    ConnectRequest,
    DeleteRequest,
    DrawingDetails,
    EntityMetadata,
    MoveRequest,
    RotateRequest,
    SymbolInsertRequest,
)

controller = AutoCADController()
_controller_lock = RLock()
_COM_RETRYABLE_SIGNATURES = ("-2147418111", "call was rejected by callee")


def _is_retryable_com_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(signature in message for signature in _COM_RETRYABLE_SIGNATURES)


def _with_com_retry(operation: str, fn, attempts: int = 4, delay_seconds: float = 0.2):
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if not _is_retryable_com_error(exc) or attempt == attempts:
                raise
            wait = delay_seconds * attempt
            logger.warning(
                "[COM-RETRY] %s failed (attempt %s/%s): %s. Retrying in %.2fs",
                operation,
                attempt,
                attempts,
                exc,
                wait,
            )
            time.sleep(wait)
    if last_exc:
        raise last_exc


def _ensure_controller_ready() -> None:
    connected = _with_com_retry("ensure_connected", controller.connect, attempts=3, delay_seconds=0.15)
    if not connected:
        raise RuntimeError("AutoCAD connection failed")

def get_available_symbols() -> List[str]:
    """Load all available symbol names from symbol_templates.json"""
    template_path = Path(__file__).resolve().parent / "symbol_templates.json"
    try:
        with template_path.open("r", encoding="utf-8") as f:
            templates = json.load(f)
        if isinstance(templates, dict):
            return sorted(list(templates.keys()))
    except Exception as exc:
        logger.error("Error loading symbols: %s", exc)
    return []

def connect_autocad() -> bool:
    with _controller_lock:
        return _with_com_retry("connect", controller.connect)

def get_status() -> Dict[str, Optional[str]]:
    with _controller_lock:
        connected = controller.is_connected()
        return {
            "connected": connected,
            "document": controller.get_active_document_name() if connected else None,
        }

def get_entities() -> List[EntityMetadata]:
    with _controller_lock:
        _ensure_controller_ready()
        _with_com_retry("sync_modelspace_entities", controller.sync_modelspace_entities)
        return [EntityMetadata(**meta) for meta in controller.get_tracked_entities()]

def refresh_entities() -> List[EntityMetadata]:
    with _controller_lock:
        _ensure_controller_ready()
        _with_com_retry("refresh_modelspace_entities", controller.sync_modelspace_entities)
        return [EntityMetadata(**meta) for meta in controller.get_tracked_entities()]


def get_entity(handle: str) -> EntityMetadata:
    with _controller_lock:
        _ensure_controller_ready()
        _with_com_retry("sync_modelspace_entities", controller.sync_modelspace_entities)
        tracked = controller.get_registry_entity(handle)
        if tracked:
            return EntityMetadata(**tracked)
        try:
            entity = _with_com_retry("get_entity_by_handle", lambda: controller.get_entity_by_handle(handle))
            return EntityMetadata(**_with_com_retry("entity_metadata", lambda: controller.entity_metadata(entity)))
        except Exception:
            raise

def insert_symbol(request: SymbolInsertRequest) -> EntityMetadata:
    with _controller_lock:
        _ensure_controller_ready()
        entity = _with_com_retry(
            "insert_symbol",
            lambda: controller.insert_symbol(
                request.block_name,
                (request.x, request.y),
                request.rotation,
                request.layer,
                scale=request.scale,
            ),
        )
        _with_com_retry("sync_modelspace_entities_after_insert", controller.sync_modelspace_entities)
        return EntityMetadata(**_with_com_retry("entity_metadata_after_insert", lambda: controller.entity_metadata(entity)))

def delete_entity(request: DeleteRequest) -> Dict[str, str]:
    with _controller_lock:
        _ensure_controller_ready()
        _with_com_retry("delete_entity", lambda: controller.delete_entity(request.handle))
        _with_com_retry("sync_modelspace_entities_after_delete", controller.sync_modelspace_entities)
        return {"deleted": request.handle}

def move_entity(request: MoveRequest) -> EntityMetadata:
    with _controller_lock:
        _ensure_controller_ready()
        _with_com_retry("move_entity", lambda: controller.move_entity(request.handle, request.dx, request.dy, request.dz))
        _with_com_retry("sync_modelspace_entities_after_move", controller.sync_modelspace_entities)
        tracked = controller.get_registry_entity(request.handle)
        if tracked:
            return EntityMetadata(**tracked)
        entity = _with_com_retry("get_entity_by_handle_after_move", lambda: controller.get_entity_by_handle(request.handle))
        return EntityMetadata(**_with_com_retry("entity_metadata_after_move", lambda: controller.entity_metadata(entity)))

def rotate_entity(request: RotateRequest) -> EntityMetadata:
    with _controller_lock:
        _ensure_controller_ready()
        _with_com_retry(
            "rotate_entity",
            lambda: controller.rotate_entity(
                request.handle,
                request.angle,
                (request.base_x, request.base_y, request.base_z),
            ),
        )
        _with_com_retry("sync_modelspace_entities_after_rotate", controller.sync_modelspace_entities)
        tracked = controller.get_registry_entity(request.handle)
        if tracked:
            return EntityMetadata(**tracked)
        entity = _with_com_retry("get_entity_by_handle_after_rotate", lambda: controller.get_entity_by_handle(request.handle))
        return EntityMetadata(**_with_com_retry("entity_metadata_after_rotate", lambda: controller.entity_metadata(entity)))

def count_entities() -> int:
    with _controller_lock:
        _ensure_controller_ready()
        _with_com_retry("sync_modelspace_entities_for_count", controller.sync_modelspace_entities)
        return controller.count_entities()

def get_drawing_details() -> DrawingDetails:
    with _controller_lock:
        _ensure_controller_ready()
        _with_com_retry("sync_modelspace_entities_for_drawing_details", controller.sync_modelspace_entities)
        return DrawingDetails(
            document_name=controller.get_active_document_name(),
            modelspace_count=controller.modelspace_count(),
            block_definitions=controller.block_definitions(),
            layers=controller.document_layers(),
        )

def connect_instruments(request: ConnectRequest) -> Dict[str, str]:
    with _controller_lock:
        _ensure_controller_ready()
        pipe_handle = _with_com_retry(
            "connect_instruments",
            lambda: route_orthogonal_pipe(
                controller,
                request.start_handle,
                request.end_handle,
            ),
        )
        _with_com_retry("sync_modelspace_entities_after_connect", controller.sync_modelspace_entities)
        return {"connected": pipe_handle}
