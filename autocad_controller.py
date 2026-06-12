import logging
import math
import re
import uuid
import json
import time
from typing import Dict, List, Optional, Tuple, Any

import pythoncom
import win32com.client
from win32com.client import VARIANT

from com_utils import to_variant_point, to_variant_points
from symbol_renderer import SymbolRenderer, EQUIPMENT_LAYER, PIPES_LAYER

Point2D = Tuple[float, float]
Point3D = Tuple[float, float, float]

logger = logging.getLogger(__name__)


class AutoCADController:
    def __init__(self):
        self.acad = None
        self.doc = None
        self.modelspace = None
        self.renderer = SymbolRenderer()
        self.entity_registry: Dict[str, Dict[str, Any]] = {}
        self.connections: Dict[str, List[str]] = {}
        self.primitive_owners: Dict[str, str] = {}
        self.deleted_handles: set = set()

    def _log(self, category: str, message: str) -> None:
        logger.info("[%s] %s", category, message)

    def resolve_logical_handle(self, handle: str) -> str:
        if handle in self.entity_registry:
            return handle
        owner = self.primitive_owners.get(handle)
        if owner:
            self._log("OWNERSHIP", f"Resolved primitive {handle} -> {owner}")
            return owner
        return handle

    def _looks_like_raw_autocad_handle(self, handle: str) -> bool:
        """True for COM ModelSpace primitive handles (hex), never for SYM_/PIPE_/CAD_ logical ids."""
        if not handle or not isinstance(handle, str):
            return False
        h = handle.strip()
        upper = h.upper()
        if upper.startswith("SYM_") or upper.startswith("PIPE_") or upper.startswith("CAD_"):
            return False
        return bool(re.fullmatch(r"[0-9A-Fa-f]+", h))

    def _register_primitive_owner(self, primitive_handle: str, owner_handle: str) -> None:
        self.primitive_owners[primitive_handle] = owner_handle
        self._log("OWNERSHIP", f"Registered primitive {primitive_handle} -> {owner_handle}")

    def _cleanup_primitive_owners(self, owner_handle: str) -> None:
        for primitive_handle, owner in list(self.primitive_owners.items()):
            if owner == owner_handle:
                del self.primitive_owners[primitive_handle]
                self._log("OWNERSHIP", f"Removed ownership mapping for {primitive_handle} -> {owner_handle}")

    def connect(self) -> bool:
        pythoncom.CoInitialize()
        self._log("COM", "Starting AutoCAD connection")

        app = None
        try:
            self._log("COM", "Trying GetObject")
            app = win32com.client.GetObject(None, "AutoCAD.Application")
            self._log("COM", "GetObject success")
        except Exception as e:
            self._log("COM", f"GetObject failed: {e}")
            try:
                self._log("COM", "Trying Dispatch")
                app = win32com.client.Dispatch("AutoCAD.Application")
                self._log("COM", "Dispatch success")
            except Exception as e2:
                self._log("COM", f"Dispatch failed: {e2}. Trying EnsureDispatch")
                try:
                    app = win32com.client.gencache.EnsureDispatch("AutoCAD.Application")
                    self._log("COM", "EnsureDispatch success")
                except Exception as e3:
                    self._log("COM", f"EnsureDispatch failed: {e3}")
                    return False

        self.acad = app
        try:
            try:
                self.acad.Visible = True
            except Exception:
                pass

            self.doc = self._resolve_document(self.acad)
            if self.doc is None:
                self._log("COM", "Unable to resolve or create an AutoCAD document")
                return False

            try:
                self._log("COM", f"ActiveDocument = {self.doc.Name}")
            except Exception:
                self._log("COM", "ActiveDocument resolved but Name property unavailable")

            self.modelspace = self.doc.ModelSpace
            self._log("COM", "ModelSpace assigned")
        except Exception as e:
            logger.exception("[COM] Document/modelspace initialization failed: %s", e)
            return False

        if not hasattr(self.doc, "ModelSpace"):
            self._log("COM", "ActiveDocument has no ModelSpace")
            return False

        self._ensure_layers()
        self.register_app()
        self.sync_modelspace_entities()
        self._log("COM", "Connect success")
        return True

    def _resolve_document(self, app):
        last_exc: Exception | None = None
        for attempt in range(1, 6):
            try:
                doc = app.ActiveDocument
                _ = doc.ModelSpace
                return doc
            except Exception as active_exc:
                last_exc = active_exc
                self._log("COM", f"ActiveDocument retrieval failed (attempt {attempt}/5): {active_exc}")

            try:
                docs = app.Documents
                doc_count = int(getattr(docs, "Count", 0))
                self._log("COM", f"Documents count = {doc_count}")
                if doc_count > 0:
                    try:
                        for idx in (0, 1, doc_count - 1):
                            if idx < 0 or idx >= doc_count:
                                continue
                            try:
                                doc = docs.Item(idx)
                                _ = doc.ModelSpace
                                self._log("COM", f"Using fallback document index={idx}")
                                return doc
                            except Exception:
                                continue
                    except Exception as item_exc:
                        last_exc = item_exc
                else:
                    self._log("COM", "No open drawing found, creating new drawing")
                    try:
                        doc = docs.Add()
                    except Exception:
                        # Some COM wrappers expose Add on app.Documents only through a fresh property lookup.
                        doc = app.Documents.Add()
                    _ = doc.ModelSpace
                    return doc
            except Exception as docs_exc:
                last_exc = docs_exc
                self._log("COM", f"Document collection access failed (attempt {attempt}/5): {docs_exc}")

            try:
                pythoncom.PumpWaitingMessages()
            except Exception:
                pass
            time.sleep(0.25 * attempt)

        if last_exc:
            self._log("COM", f"Document resolution exhausted retries: {last_exc}")
        return None

    def refresh_document(self):
        """
        Force AutoCAD viewport/database refresh after geometry modifications.
        """

        self._log("VIEW", "Refreshing AutoCAD document")

        try:
            self.doc.Regen(1)
            self._log("VIEW", "Document regenerated")
        except Exception as exc:
            self._log("VIEW", f"Regen failed: {exc}")

        try:
            self.acad.Update()
            self._log("VIEW", "Application updated")
        except Exception as exc:
            self._log("VIEW", f"Application update failed: {exc}")

        try:
            pythoncom.PumpWaitingMessages()
            self._log("VIEW", "COM messages pumped")
        except Exception as exc:
            self._log("VIEW", f"PumpWaitingMessages failed: {exc}")

    def register_app(self, app_name="DIGIPID"):
        try:
            reg_apps = self.doc.RegisteredApplications
            reg_apps.Add(app_name)
        except Exception:
            pass

    def attach_xdata(self, entity, data: dict, app_name="DIGIPID"):
        """
        Persist logical metadata inside DWG entity.
        """

        try:
            json_data = json.dumps(data)

            xdata_type = VARIANT(
                pythoncom.VT_ARRAY | pythoncom.VT_I2,
                [1001, 1000]
            )

            xdata_value = VARIANT(
                pythoncom.VT_ARRAY | pythoncom.VT_VARIANT,
                [app_name, json_data]
            )

            entity.SetXData(xdata_type, xdata_value)

            self._log(
                "XDATA",
                f"Attached XData to {entity.Handle}: {json_data}"
            )

        except Exception as exc:
            self._log(
                "XDATA",
                f"Failed attaching XData: {exc}"
            )

    def read_xdata(self, entity, app_name="DIGIPID"):
        try:
            data = entity.GetXData(app_name)

            if not data:
                return None

            values = data[1]

            if len(values) < 2:
                return None

            json_data = values[1]

            return json.loads(json_data)

        except Exception as exc:
            self._log(
                "XDATA",
                f"Failed reading XData from {entity.Handle}: {exc}"
            )
            return None

    def is_connected(self) -> bool:
        return self.acad is not None and self.doc is not None and self.modelspace is not None

    def get_active_document_name(self) -> str:
        return getattr(self.doc, "Name", "<unknown>")

    def _ensure_layers(self) -> None:
        layers = self.doc.Layers
        for layer_name, color in ((EQUIPMENT_LAYER, 3), (PIPES_LAYER, 5)):
            try:
                layers.Item(layer_name)
            except Exception:
                try:
                    new_layer = layers.Add(layer_name)
                    new_layer.Color = color
                except Exception as exc:
                    self._log("LAYER", f"Failed to create layer '{layer_name}': {exc}")

    def _ensure_layer(self, layer_name: str) -> None:
        layers = self.doc.Layers
        try:
            layers.Item(layer_name)
        except Exception:
            try:
                new_layer = layers.Add(layer_name)
                new_layer.Color = 3
            except Exception as exc:
                self._log("LAYER", f"Failed to create layer '{layer_name}': {exc}")

    def zoom_extents(self) -> None:
        if not self.is_connected():
            return
        try:
            self.doc.SendCommand("_ZOOM E ")
            self._log("VIEW", "Zoom extents command sent")
        except Exception as exc:
            self._log("VIEW", f"Zoom extents failed: {exc}")

    def get_modelspace_entities(self) -> List:
        if not self.is_connected():
            return []
        entities = []
        try:
            count = int(self.modelspace.Count)
            for i in range(count):
                try:
                    entities.append(self.modelspace.Item(i))
                except Exception as exc:
                    self._log("SYNC", f"Failed to read ModelSpace item {i}: {exc}")
        except Exception as exc:
            self._log("SYNC", f"Failed to enumerate ModelSpace: {exc}")
        return entities

    def get_tracked_entities(self) -> List[Dict[str, Any]]:
        return list(self.entity_registry.values())

    def get_registry_entity(self, handle: str) -> Optional[Dict[str, Any]]:
        logical_handle = self.resolve_logical_handle(handle)
        return self.entity_registry.get(logical_handle)

    def get_entity_by_handle(self, handle: str):
        if not self.is_connected():
            raise RuntimeError("AutoCAD is not connected")

        def _resolve_once() -> Optional[Any]:
            if self._looks_like_raw_autocad_handle(handle):
                try:
                    return self.doc.HandleToObject(handle)
                except Exception:
                    pass

            logical_handle = self.resolve_logical_handle(handle)
            entry = self.entity_registry.get(logical_handle)
            if entry:
                raw_handles = entry.get("entity_handles") or entry.get("segment_handles") or []
                for raw in raw_handles:
                    if not self._looks_like_raw_autocad_handle(str(raw)):
                        continue
                    try:
                        ent = self.doc.HandleToObject(str(raw))
                        self._log(
                            "OWNERSHIP",
                            f"Resolved logical entity {logical_handle} to raw handle {raw}",
                        )
                        return ent
                    except Exception:
                        continue

            if self._looks_like_raw_autocad_handle(handle):
                return self.doc.HandleToObject(handle)
            return None

        entity = _resolve_once()
        if entity is not None:
            return entity

        self._log("COM", f"get_entity_by_handle retry after sync for {handle!r}")
        self.sync_modelspace_entities()
        entity = _resolve_once()
        if entity is not None:
            return entity

        raise RuntimeError(
            f"Unknown entity handle {handle!r}: not in drawing registry. "
            "Refresh the entity list and pick current handles."
        )

    def is_entity_alive(self, entity) -> bool:
        try:
            _ = entity.Handle
            _ = entity.ObjectName
            return True
        except Exception:
            return False

    def sync_modelspace_entities(self) -> None:
        if not self.is_connected():
            return
        logger.info("[SYNC] Starting ModelSpace synchronization")

        # First pass: Rebuild ownership graph from XData
        self._log("SYNC", "Rebuilding ownership graph from XData")
        xdata_ownership = {}  # logical_handle -> list of primitive_handles
        xdata_metadata = {}  # logical_handle -> metadata dict

        for i in range(int(self.modelspace.Count)):
            try:
                entity = self.modelspace.Item(i)
                if not self.is_entity_alive(entity):
                    self._log("SYNC", f"Skipping dead ModelSpace entity at index {i}")
                    continue

                handle = self._handle_for(entity)
                if not handle:
                    continue

                if handle in self.deleted_handles:
                    self._log("SYNC", f"Skipping deleted handle {handle}")
                    continue

                xdata = self.read_xdata(entity)
                if xdata:
                    logical_handle = xdata.get("logical_handle")
                    if logical_handle:
                        if logical_handle not in xdata_ownership:
                            xdata_ownership[logical_handle] = []
                            xdata_metadata[logical_handle] = xdata
                        xdata_ownership[logical_handle].append(handle)
                        self._register_primitive_owner(handle, logical_handle)
                        self._log("XDATA", f"Recovered primitive {handle} -> {logical_handle}")

            except Exception as exc:
                self._log("SYNC", f"Failed to read XData from entity at index {i}: {exc}")

        # Reconstruct logical entities from XData
        for logical_handle, primitive_handles in xdata_ownership.items():
            metadata = xdata_metadata[logical_handle]
            entity_type = metadata.get("entity_type", "unknown")

            if entity_type == "symbol":
                stored_insertion_point = metadata.get("insertion_point")
                if isinstance(stored_insertion_point, list) and len(stored_insertion_point) >= 2:
                    stored_insertion_point = (
                        float(stored_insertion_point[0]),
                        float(stored_insertion_point[1]),
                        float(stored_insertion_point[2]) if len(stored_insertion_point) > 2 else 0.0,
                    )
                elif isinstance(stored_insertion_point, tuple) and len(stored_insertion_point) >= 2:
                    stored_insertion_point = (
                        float(stored_insertion_point[0]),
                        float(stored_insertion_point[1]),
                        float(stored_insertion_point[2]) if len(stored_insertion_point) > 2 else 0.0,
                    )
                else:
                    stored_insertion_point = None

                # Always prefer live geometry-derived position so moved symbols do not
                # keep stale insertion points from older XData.
                geometry_insertion_point = self._recover_symbol_insertion_point(primitive_handles)
                recovered_insertion_point = geometry_insertion_point or stored_insertion_point

                self.entity_registry[logical_handle] = {
                    "handle": logical_handle,
                    "entity_type": "symbol",
                    "block_name": metadata.get("block_name"),
                    "layer": metadata.get("layer", EQUIPMENT_LAYER),
                    "insertion_point": recovered_insertion_point,
                    "rotation": metadata.get("rotation", 0.0),
                    "scale": metadata.get("scale", 100.0),
                    "primitive_count": len(primitive_handles),
                    "entity_handles": primitive_handles,
                    "group_handle": None,
                    "vertices": None,
                    "radius": None,
                    "start_handle": None,
                    "end_handle": None,
                    "segment_handles": None,
                    "route_points": None,
                    "connected_entities": [],
                    "metadata": {"block_reference": metadata.get("block_name")},
                }
                self._log("SYNC", f"Reconstructed symbol {logical_handle} with {len(primitive_handles)} primitives")

            elif entity_type == "pipe_segment":
                pipe_handle = metadata.get("logical_handle")
                if not pipe_handle:
                    continue
                if pipe_handle not in xdata_ownership:
                    xdata_ownership[pipe_handle] = []
                    xdata_metadata[pipe_handle] = {
                        "entity_type": "pipe",
                        "start_handle": metadata.get("start_handle"),
                        "end_handle": metadata.get("end_handle"),
                    }
                xdata_ownership[pipe_handle].append(handle)

        # Now reconstruct pipes
        for pipe_handle, segment_handles in xdata_ownership.items():
            if pipe_handle.startswith("PIPE_"):
                metadata = xdata_metadata.get(pipe_handle, {})
                self.entity_registry[pipe_handle] = {
                    "handle": pipe_handle,
                    "entity_type": "pipe",
                    "layer": PIPES_LAYER,
                    "block_name": None,
                    "insertion_point": None,
                    "rotation": None,
                    "scale": None,
                    "primitive_count": len(segment_handles),
                    "entity_handles": segment_handles,
                    "group_handle": None,
                    "vertices": None,
                    "radius": None,
                    "start_handle": metadata.get("start_handle"),
                    "end_handle": metadata.get("end_handle"),
                    "segment_handles": segment_handles,
                    "route_points": None,  # Would need to reconstruct from segments
                    "connected_entities": [metadata.get("start_handle"), metadata.get("end_handle")],
                    "metadata": {"pipe_type": "orthogonal"},
                }
                self._log("SYNC", f"Reconstructed pipe {pipe_handle} with {len(segment_handles)} segments")

        current_handles = set()
        pipe_segment_handles = set(
            seg for entity in self.entity_registry.values()
            if entity.get("entity_type") == "pipe"
            for seg in entity.get("segment_handles", []) or []
        )
        logger.info(f"[SYNC] Existing handles count: {len(self.entity_registry)}")
        logger.info(f"[SYNC] Pipe segment handles to skip: {len(pipe_segment_handles)}")

        for i in range(int(self.modelspace.Count)):
            try:
                entity = self.modelspace.Item(i)
                if not self.is_entity_alive(entity):
                    self._log("SYNC", f"Skipping dead ModelSpace entity at index {i}")
                    continue

                handle = self._handle_for(entity)
                if not handle:
                    continue

                if handle in self.deleted_handles:
                    self._log("SYNC", f"Skipping deleted handle {handle}")
                    continue

                current_handles.add(handle)

                if handle in self.primitive_owners:
                    owner = self.primitive_owners[handle]
                    if owner in self.entity_registry:
                        self._log("SYNC", f"Skipping owned primitive {handle}, owner={owner}")
                        continue
                    self._log("SYNC", f"Removing stale ownership mapping for {handle}, orphan owner={owner}")
                    del self.primitive_owners[handle]

                metadata = self._extract_entity_metadata(entity)
                entity_type = metadata.get("entity_type", "unknown")

                if handle in self.entity_registry:
                    if self._has_metadata_changed(self.entity_registry[handle], metadata):
                        self.entity_registry[handle].update(metadata)
                        logger.info(f"[SYNC] Updated entity: {handle} ({entity_type})")
                else:
                    logical_handle = f"CAD_{handle}"
                    metadata["handle"] = logical_handle
                    metadata["entity_type"] = "cad_entity"
                    metadata["entity_handles"] = [handle]
                    metadata["primitive_handles"] = [handle]
                    metadata["primitive_count"] = 1
                    self.entity_registry[logical_handle] = metadata
                    self._register_primitive_owner(handle, logical_handle)
                    logger.info(f"[SYNC] Detected unmanaged CAD entity {logical_handle} from primitive {handle}")

            except Exception as exc:
                logger.warning(f"[SYNC] Failed to scan ModelSpace entity at index {i}: {exc}")

        stale_handles = []
        for logical_handle, entry in self.entity_registry.items():
            raw_handles = entry.get("entity_handles") or entry.get("segment_handles") or []
            if not raw_handles:
                continue
            if not any(raw_handle in current_handles for raw_handle in raw_handles):
                stale_handles.append(logical_handle)

        logger.info(f"[SYNC] Found {len(stale_handles)} stale logical entities to remove")
        for handle in stale_handles:
            logger.info(f"[SYNC] Removing stale logical entity {handle}")
            self._remove_entity(handle, remove_segments=False)

        self._cleanup_broken_pipes(current_handles)
        self._sync_topology()
        self.deleted_handles = {h for h in self.deleted_handles if h in current_handles}
        logger.info(f"[SYNC] Deleted handle cache retained: {len(self.deleted_handles)} entries")
        logger.info("[SYNC] Synchronization complete")

    def _cleanup_broken_pipes(self, current_handles: set) -> None:
        for pipe_handle, entry in list(self.entity_registry.items()):
            if entry.get("entity_type") != "pipe":
                continue
            missing = [seg for seg in entry.get("segment_handles", []) if seg not in current_handles]
            if missing:
                self._log("SYNC", f"Pipe {pipe_handle} lost segment handles {missing}; unregistering pipe")
                self._remove_pipe(pipe_handle)

    def _sync_topology(self) -> None:
        self.connections = {}
        for handle, entry in self.entity_registry.items():
            if entry.get("entity_type") != "pipe":
                continue
            start = entry.get("start_handle")
            end = entry.get("end_handle")
            for endpoint in (start, end):
                if not endpoint:
                    continue
                self.connections.setdefault(endpoint, []).append(handle)
        self._log("TOPO", f"Topology graph updated: {self.connections}")

    def _has_metadata_changed(self, existing: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
        keys = [
            "entity_type",
            "layer",
            "insertion_point",
            "rotation",
            "scale",
            "block_name",
            "vertices",
            "radius",
        ]
        for key in keys:
            if existing.get(key) != candidate.get(key):
                return True
        return False

    def _handle_for(self, entity) -> Optional[str]:
        try:
            handle = str(entity.Handle)
            return handle
        except Exception as exc:
            self._log("COM", f"Failed to read entity handle: {exc}")
            return None

    def _get_entity_type(self, entity) -> str:
        try:
            entity_name = getattr(entity, "EntityName", None)
            if isinstance(entity_name, str):
                value = entity_name.lower()
            else:
                value = type(entity).__name__.lower()
        except Exception:
            value = type(entity).__name__.lower()

        if "acdbline" in value:
            return "line"
        if "acdbcircle" in value:
            return "circle"
        if "acdbpolyline" in value:
            return "polyline"
        if "acdblightweightpolyline" in value:
            return "lightweight_polyline"
        if "acdbhatch" in value or "hatch" in value:
            return "hatch"
        if "acdbtext" in value or "dbtext" in value or "text" in value:
            return "text"
        if "acdbblockreference" in value or "blockreference" in value:
            return "block_reference"
        return value.replace("acdb", "")

    def _primitive_type_for_entity(self, entity) -> str:
        entity_type = self._get_entity_type(entity)
        if entity_type == "line":
            return "line"
        if entity_type in ("polyline", "lightweight_polyline"):
            return "contour"
        if entity_type == "circle":
            return "circle"
        if entity_type == "text":
            return "text"
        if entity_type == "hatch":
            return "hatch"
        return "symbol_part"

    def _to_point3d(self, source) -> Optional[Point3D]:
        try:
            return (float(source[0]), float(source[1]), float(source[2]))
        except Exception:
            return None

    def _extract_vertices(self, coordinates) -> Optional[List[Point3D]]:
        try:
            coords = list(coordinates)
            if not coords:
                return None

            vertices: List[Point3D] = []

            # Detect coordinate format: XYXY... or XYZXYZ...
            coord_count = len(coords)
            if coord_count % 2 == 0 and coord_count % 3 != 0:
                # XY format: [x1, y1, x2, y2, ...]
                logger.info(f"[SYNC] Extracting polyline vertices - detected XY format with {coord_count//2} points")
                for idx in range(0, coord_count, 2):
                    x, y = float(coords[idx]), float(coords[idx + 1])
                    vertices.append((x, y, 0.0))
            elif coord_count % 3 == 0:
                # XYZ format: [x1, y1, z1, x2, y2, z2, ...]
                logger.info(f"[SYNC] Extracting polyline vertices - detected XYZ format with {coord_count//3} points")
                for idx in range(0, coord_count, 3):
                    x, y, z = float(coords[idx]), float(coords[idx + 1]), float(coords[idx + 2])
                    vertices.append((x, y, z))
            else:
                logger.info(f"[SYNC] Extracting polyline vertices - unknown coordinate format with {coord_count} values")
                return None

            logger.info(f"[SYNC] Extracted {len(vertices)} vertices")
            return vertices if vertices else None
        except Exception as exc:
            logger.warning(f"[SYNC] Failed to extract vertices: {exc}")
            return None

    def _extract_entity_metadata(self, entity) -> Dict[str, Any]:
        handle = self._handle_for(entity)
        entity_type = self._get_entity_type(entity)
        layer = getattr(entity, "Layer", None)
        rotation = None
        try:
            rotation = float(getattr(entity, "Rotation", 0.0))
        except Exception:
            rotation = None

        insertion_point = None
        if hasattr(entity, "InsertionPoint"):
            insertion_point = self._to_point3d(entity.InsertionPoint)

        metadata: Dict[str, Any] = {
            "handle": handle,
            "entity_type": entity_type,
            "layer": layer,
            "rotation": rotation,
            "scale": None,
            "raw_type": str(getattr(entity, "EntityName", type(entity).__name__)),
            "insertion_point": insertion_point,
            "block_name": None,
            "primitive_count": None,
            "vertices": None,
            "radius": None,
            "start_handle": None,
            "end_handle": None,
            "segment_handles": None,
            "route_points": None,
            "connected_entities": None,
            "metadata": {"raw_entity_name": getattr(entity, "EntityName", None)},
        }

        if entity_type == "line":
            try:
                start = self._to_point3d(entity.StartPoint)
                end = self._to_point3d(entity.EndPoint)
                metadata["vertices"] = [start, end] if start and end else None
                if insertion_point is None:
                    metadata["insertion_point"] = start or end
                metadata["primitive_count"] = 1
            except Exception as exc:
                self._log("SYNC", f"Failed to extract line metadata {handle}: {exc}")

        elif entity_type in ("polyline", "lightweight_polyline"):
            coords = getattr(entity, "Coordinates", None)
            vertices = self._extract_vertices(coords)
            metadata["vertices"] = vertices
            metadata["primitive_count"] = len(vertices) if vertices else None
            if insertion_point is None and vertices:
                metadata["insertion_point"] = vertices[0]

        elif entity_type == "circle":
            try:
                center = self._to_point3d(entity.Center)
                metadata["vertices"] = [center] if center else None
                metadata["radius"] = float(getattr(entity, "Radius", 0.0))
                metadata["primitive_count"] = 1
                if insertion_point is None:
                    metadata["insertion_point"] = center
            except Exception as exc:
                self._log("SYNC", f"Failed to extract circle metadata {handle}: {exc}")

        elif entity_type == "block_reference":
            try:
                metadata["block_name"] = str(getattr(entity, "Name", getattr(entity, "EffectiveName", None)))
                metadata["primitive_count"] = None
                if insertion_point is None and hasattr(entity, "InsertionPoint"):
                    metadata["insertion_point"] = self._to_point3d(entity.InsertionPoint)
            except Exception as exc:
                self._log("SYNC", f"Failed to extract block metadata {handle}: {exc}")

        metadata["metadata"]["layer"] = layer
        return metadata

    def _recover_symbol_insertion_point(self, primitive_handles: List[str]) -> Optional[Point3D]:
        points: List[Point3D] = []
        for primitive_handle in primitive_handles:
            try:
                primitive_entity = self.doc.HandleToObject(primitive_handle)
                primitive_meta = self._extract_entity_metadata(primitive_entity)
                insertion = primitive_meta.get("insertion_point")
                if isinstance(insertion, (list, tuple)) and len(insertion) >= 2:
                    points.append(
                        (
                            float(insertion[0]),
                            float(insertion[1]),
                            float(insertion[2]) if len(insertion) > 2 else 0.0,
                        )
                    )
            except Exception:
                continue

        if not points:
            return None

        if len(points) == 1:
            return points[0]

        count = float(len(points))
        return (
            sum(point[0] for point in points) / count,
            sum(point[1] for point in points) / count,
            sum(point[2] for point in points) / count,
        )

    def insert_symbol(
        self,
        symbol_name: str,
        insertion_point: Tuple[float, float],
        rotation: float,
        layer: str,
        scale: float = 100.0,
    ):
        if not self.is_connected():
            raise RuntimeError("AutoCAD is not connected")

        x, y = insertion_point
        self._ensure_layer(layer)

        entities = self.renderer.render_symbol(
            self.modelspace,
            symbol_name,
            x,
            y,
            scale=scale,
            rotation=rotation,
            layer=layer,
        )
        if not entities:
            raise RuntimeError(f"Symbol rendering failed for '{symbol_name}'")

        logical_handle = f"SYM_{uuid.uuid4().hex[:8]}"
        group_handle = None
        group = self._create_symbol_group()
        entity_handles: List[str] = []
        for entity in entities:
            try:
                raw_handle = str(entity.Handle)
                entity_handles.append(raw_handle)
                self._register_primitive_owner(raw_handle, logical_handle)

                primitive_type = self._primitive_type_for_entity(entity)
                self.attach_xdata(
                    entity,
                    {
                        "logical_handle": logical_handle,
                        "entity_type": "symbol",
                        "block_name": symbol_name,
                        "primitive_type": primitive_type,
                        "insertion_point": (x, y, 0.0),
                        "rotation": rotation,
                        "scale": scale,
                        "layer": layer,
                    }
                )

                if group is not None:
                    try:
                        group.Append(entity)
                    except Exception as exc:
                        self._log("SYM", f"Failed to append entity to symbol group: {exc}")
            except Exception as exc:
                logger.exception(
                    "[SYM] Failed to capture entity handle for '%s': %s",
                    symbol_name,
                    exc,
                )

        if group is not None:
            try:
                group_handle = str(group.Handle)
            except Exception:
                group_handle = None

        if not entity_handles:
            raise RuntimeError(f"Unable to resolve any symbol entity handles for '{symbol_name}'")

        self.entity_registry[logical_handle] = {
            "handle": logical_handle,
            "entity_type": "symbol",
            "block_name": symbol_name,
            "layer": layer,
            "insertion_point": (x, y, 0.0),
            "rotation": rotation,
            "scale": scale,
            "primitive_count": len(entity_handles),
            "entity_handles": entity_handles,
            "primitive_handles": entity_handles,
            "group_handle": group_handle,
            "vertices": None,
            "radius": None,
            "start_handle": None,
            "end_handle": None,
            "segment_handles": None,
            "route_points": None,
            "connected_entities": [],
            "metadata": {"block_reference": symbol_name},
        }

        self._log(
            "SYM",
            f"Registered logical symbol {logical_handle} for '{symbol_name}' insertion=({x},{y}) rotation={rotation} scale={scale} primitives={len(entity_handles)}",
        )

        self._sync_topology()
        self.sync_modelspace_entities()
        self.refresh_document()
        try:
            self.zoom_extents()
        except Exception as exc:
            self._log("VIEW", f"Zoom extents failed after insertion: {exc}")

        return entities[0]

    def _create_symbol_group(self):
        try:
            group_name = f"SYMBOL_{uuid.uuid4().hex}"
            groups = self.doc.Groups
            return groups.Add(group_name)
        except Exception as exc:
            self._log("SYM", f"Failed to create symbol group: {exc}")
            return None

    def create_pipe(self, start_handle: str, end_handle: str, route_points: List[Point3D], layer: str = PIPES_LAYER) -> str:
        if not self.is_connected():
            raise RuntimeError("AutoCAD is not connected")

        self._ensure_layer(layer)

        if start_handle == end_handle:
            raise ValueError("Start and end handles cannot be identical")

        segment_handles: List[str] = []
        created_segments = []
        try:
            for index in range(len(route_points) - 1):
                start_point = route_points[index]
                end_point = route_points[index + 1]
                line = self._create_line_segment(start_point, end_point, layer)
                segment_handles.append(str(line.Handle))
                created_segments.append(line)
        except Exception as exc:
            self._log("PIPE", f"Failed to create pipe segment: {exc}")
            for segment in created_segments:
                try:
                    segment.Delete()
                except Exception:
                    pass
            raise

        pipe_handle = f"PIPE_{uuid.uuid4().hex[:8]}"
        for segment_handle in segment_handles:
            self._register_primitive_owner(segment_handle, pipe_handle)
            
            # Attach XData to persist pipe ownership
            segment_entity = self.doc.HandleToObject(segment_handle)
            self.attach_xdata(
                segment_entity,
                {
                    "logical_handle": pipe_handle,
                    "entity_type": "pipe_segment",
                    "start_handle": start_handle,
                    "end_handle": end_handle,
                }
            )

        self.entity_registry[pipe_handle] = {
            "handle": pipe_handle,
            "entity_type": "pipe",
            "layer": layer,
            "block_name": None,
            "insertion_point": None,
            "rotation": None,
            "scale": None,
            "primitive_count": len(segment_handles),
            "entity_handles": segment_handles,
            "primitive_handles": segment_handles,
            "group_handle": None,
            "vertices": None,
            "radius": None,
            "start_handle": start_handle,
            "end_handle": end_handle,
            "segment_handles": segment_handles,
            "route_points": route_points,
            "connected_entities": [start_handle, end_handle],
            "metadata": {"pipe_type": "orthogonal"},
        }

        self._log("PIPE", f"Registered pipe {pipe_handle} between {start_handle} and {end_handle}")
        self._sync_topology()
        self.sync_modelspace_entities()
        self.refresh_document()
        return pipe_handle

    def _create_line_segment(self, start: Point3D, end: Point3D, layer: str):
        try:
            line = self.modelspace.AddLine(to_variant_point(start), to_variant_point(end))
            line.Layer = layer
            if hasattr(line, "Color"):
                line.Color = 7
            return line
        except Exception as exc:
            self._log("PIPE", f"Failed to create COM line segment: {exc}")
            raise

    def _delete_related_pipes(self, entity_handle: str) -> None:
        connected = list(self.connections.get(entity_handle, []))
        for pipe_handle in connected:
            self._log("DELETE", f"Removing connected pipe {pipe_handle} for entity {entity_handle}")
            self._remove_pipe(pipe_handle)

    def _remove_pipe(self, pipe_handle: str) -> None:
        entry = self.entity_registry.pop(pipe_handle, None)
        if not entry:
            return
        for segment_handle in entry.get("segment_handles", []) or []:
            try:
                self.doc.HandleToObject(segment_handle).Delete()
                self.deleted_handles.add(segment_handle)
                self._log("DELETE", f"Deleted pipe segment {segment_handle}")
            except Exception as exc:
                self._log("PIPE", f"Failed to delete pipe segment {segment_handle}: {exc}")
        self._cleanup_primitive_owners(pipe_handle)
        self._sync_topology()

    def _remove_entity(self, handle: str, remove_segments: bool = True) -> None:
        logical_handle = self.resolve_logical_handle(handle)
        logger.info(f"[DELETE] Attempting delete of entity {handle} resolved to {logical_handle}")

        if logical_handle not in self.entity_registry:
            try:
                entity = self.doc.HandleToObject(handle)
                entity.Delete()
                logger.info(f"[DELETE] COM delete success for unmanaged entity {handle}")

                try:
                    self.doc.HandleToObject(handle)
                    logger.info(f"[DELETE] WARNING: Entity {handle} still exists after delete")
                    entity = self.doc.HandleToObject(handle)
                    entity.Delete()
                    logger.info(f"[DELETE] Retry delete success for {handle}")
                except Exception:
                    logger.info(f"[DELETE] Delete verification success - entity {handle} no longer exists")

            except Exception as exc:
                logger.warning(f"[DELETE] Failed to delete unmanaged entity {handle}: {exc}")
            return

        entry = self.entity_registry.get(logical_handle)
        if not entry:
            return
        entity_type = entry.get("entity_type")

        if entity_type == "pipe":
            self._remove_pipe(logical_handle)
            return

        self.entity_registry.pop(logical_handle, None)
        self._cleanup_primitive_owners(logical_handle)

        if entity_type == "symbol":
            self._delete_related_pipes(logical_handle)
            logger.info(f"[DELETE] Removing connected pipes for symbol {logical_handle}")

            group_handle = entry.get("group_handle")
            if group_handle:
                try:
                    entity = self.doc.HandleToObject(group_handle)
                    entity.Delete()
                    logger.info(f"[DELETE] Deleted symbol group {group_handle} for symbol {logical_handle}")

                    try:
                        self.doc.HandleToObject(group_handle)
                        logger.info(f"[DELETE] WARNING: Symbol group {group_handle} still exists after delete")
                    except Exception:
                        logger.info(f"[DELETE] Symbol group {group_handle} delete verification success")

                    return
                except Exception as exc:
                    logger.warning(f"[DELETE] Failed to delete symbol group {group_handle}: {exc}")

            for entity_handle in entry.get("entity_handles", []) or []:
                try:
                    entity = self.doc.HandleToObject(entity_handle)
                    entity.Delete()
                    logger.info(f"[DELETE] Deleted symbol segment {entity_handle}")

                    try:
                        self.doc.HandleToObject(entity_handle)
                        logger.info(f"[DELETE] WARNING: Symbol segment {entity_handle} still exists after delete")
                    except Exception:
                        logger.info(f"[DELETE] Symbol segment {entity_handle} delete verification success")

                except Exception as exc:
                    logger.warning(f"[DELETE] Failed to delete symbol segment {entity_handle}: {exc}")
            return

        for entity_handle in entry.get("entity_handles", []) or []:
            try:
                entity = self.doc.HandleToObject(entity_handle)
                entity.Delete()
                logger.info(f"[DELETE] Deleted entity handle {entity_handle}")

                try:
                    self.doc.HandleToObject(entity_handle)
                    logger.info(f"[DELETE] WARNING: Entity {entity_handle} still exists after delete")
                except Exception:
                    logger.info(f"[DELETE] Entity {entity_handle} delete verification success")

            except Exception as exc:
                logger.warning(f"[DELETE] Failed to delete entity handle {entity_handle}: {exc}")
                logger.info(f"[DELETE] COM delete success for unmanaged entity {handle}")

                # Verify deletion
                try:
                    self.doc.HandleToObject(handle)
                    logger.info(f"[DELETE] WARNING: Entity {handle} still exists after delete")
                    # Retry once
                    entity = self.doc.HandleToObject(handle)
                    entity.Delete()
                    logger.info(f"[DELETE] Retry delete success for {handle}")
                except Exception:
                    logger.info(f"[DELETE] Delete verification success - entity {handle} no longer exists")

            except Exception as exc:
                logger.warning(f"[DELETE] Failed to delete unmanaged entity {handle}: {exc}")
            return

        entry = self.entity_registry.pop(handle)
        entity_type = entry.get("entity_type")

        if entity_type == "pipe":
            self._remove_pipe(handle)
            return

        if entity_type == "symbol":
            self._delete_related_pipes(handle)
            logger.info(f"[DELETE] Removing connected pipes for symbol {handle}")

            group_handle = entry.get("group_handle")
            if group_handle:
                try:
                    entity = self.doc.HandleToObject(group_handle)
                    entity.Delete()
                    logger.info(f"[DELETE] Deleted symbol group {group_handle} for symbol {handle}")

                    # Verify deletion
                    try:
                        self.doc.HandleToObject(group_handle)
                        logger.info(f"[DELETE] WARNING: Symbol group {group_handle} still exists after delete")
                    except Exception:
                        logger.info(f"[DELETE] Symbol group {group_handle} delete verification success")

                    return
                except Exception as exc:
                    logger.warning(f"[DELETE] Failed to delete symbol group {group_handle}: {exc}")

            for entity_handle in entry.get("entity_handles", []) or []:
                try:
                    entity = self.doc.HandleToObject(entity_handle)
                    entity.Delete()
                    logger.info(f"[DELETE] Deleted symbol segment {entity_handle}")

                    # Verify deletion
                    try:
                        self.doc.HandleToObject(entity_handle)
                        logger.info(f"[DELETE] WARNING: Symbol segment {entity_handle} still exists after delete")
                    except Exception:
                        logger.info(f"[DELETE] Symbol segment {entity_handle} delete verification success")

                except Exception as exc:
                    logger.warning(f"[DELETE] Failed to delete symbol segment {entity_handle}: {exc}")
            return

        for entity_handle in entry.get("entity_handles", []) or []:
            try:
                entity = self.doc.HandleToObject(entity_handle)
                entity.Delete()
                logger.info(f"[DELETE] Deleted entity handle {entity_handle}")

                # Verify deletion
                try:
                    self.doc.HandleToObject(entity_handle)
                    logger.info(f"[DELETE] WARNING: Entity {entity_handle} still exists after delete")
                except Exception:
                    logger.info(f"[DELETE] Entity {entity_handle} delete verification success")

            except Exception as exc:
                logger.warning(f"[DELETE] Failed to delete entity handle {entity_handle}: {exc}")

    def _delete_raw_entity(self, primitive_handle: str) -> None:
        try:
            entity = self.doc.HandleToObject(primitive_handle)
        except Exception as exc:
            self._log("DELETE", f"HandleToObject failed for {primitive_handle}: {exc}")
            return

        if not self.is_entity_alive(entity):
            self._log("DELETE", f"Primitive already deleted: {primitive_handle}")
            self.deleted_handles.add(primitive_handle)
            return

        try:
            entity.Delete()
            self.deleted_handles.add(primitive_handle)
            self._log("DELETE", f"Deleted primitive: {primitive_handle}")
        except Exception as exc:
            self._log("DELETE", f"Failed deleting primitive {primitive_handle}: {exc}")

    def delete_entity(self, handle: str) -> None:
        if not self.is_connected():
            raise RuntimeError("AutoCAD is not connected")

        logical_handle = self.resolve_logical_handle(handle)
        entry = self.entity_registry.get(logical_handle)

        if entry:
            self._log("DELETE", f"Deleting logical entity {logical_handle} type={entry.get('entity_type')}" )
            primitive_handles = list(entry.get("primitive_handles") or entry.get("entity_handles") or [])

            if entry.get("entity_type") == "symbol":
                self._log("DELETE", f"Deleting connected pipes for symbol {logical_handle}")
                self._delete_related_pipes(logical_handle)

            group_handle = entry.get("group_handle")
            if group_handle:
                self._log("DELETE", f"Deleting symbol group {group_handle}")
                self._delete_raw_entity(group_handle)

            for primitive_handle in primitive_handles:
                self._delete_raw_entity(primitive_handle)

            self._cleanup_primitive_owners(logical_handle)
            self.entity_registry.pop(logical_handle, None)
            self._sync_topology()

        else:
            self._log("DELETE", f"Deleting unmanaged entity {handle}")
            try:
                self._delete_raw_entity(handle)
            except Exception as exc:
                self._log("DELETE", f"Failed deleting unmanaged entity {handle}: {exc}")

        self.refresh_document()
        self.sync_modelspace_entities()
        self.refresh_document()

    def move_entity(self, handle: str, dx: float, dy: float, dz: float = 0.0) -> None:
        if not self.is_connected():
            raise RuntimeError("AutoCAD is not connected")
        logical_handle = self.resolve_logical_handle(handle)
        if logical_handle != handle:
            self._log("MOVE", f"Resolved primitive {handle} -> {logical_handle}")
        entry = self.entity_registry.get(logical_handle)
        vector = (dx, dy, dz)
        if entry:
            self._log("MOVE", f"Moving logical entity {logical_handle} type={entry.get('entity_type')} vector={vector}")
            entity_type = entry.get("entity_type")
            if entity_type == "pipe":
                for segment_handle in entry.get("segment_handles", []) or []:
                    try:
                        logger.info(f"[MOVE] Moving pipe segment {segment_handle} by vector {vector}")
                        self.doc.HandleToObject(segment_handle).Move(
                            to_variant_point((0.0, 0.0, 0.0)),
                            to_variant_point(vector)
                        )
                        logger.info(f"[MOVE] Pipe segment {segment_handle} moved successfully")
                    except Exception as exc:
                        logger.warning(f"[MOVE] Failed to move pipe segment {segment_handle}: {exc}")
                self.sync_modelspace_entities()
                self.refresh_document()
                return
            if entity_type == "symbol":
                group_handle = entry.get("group_handle")
                if group_handle:
                    try:
                        logger.info(f"[MOVE] Moving symbol group {group_handle} by vector {vector}")
                        self.doc.HandleToObject(group_handle).Move(
                            to_variant_point((0.0, 0.0, 0.0)),
                            to_variant_point(vector)
                        )
                        logger.info(f"[MOVE] Symbol group {group_handle} moved successfully")
                        self.sync_modelspace_entities()
                        self.refresh_document()
                        return
                    except Exception as exc:
                        logger.warning(f"[MOVE] Symbol group move failed: {exc}")
                for entity_handle in entry.get("entity_handles", []) or []:
                    try:
                        logger.info(f"[MOVE] Moving symbol entity {entity_handle} by vector {vector}")
                        self.doc.HandleToObject(entity_handle).Move(
                            to_variant_point((0.0, 0.0, 0.0)),
                            to_variant_point(vector)
                        )
                        logger.info(f"[MOVE] Symbol entity {entity_handle} moved successfully")
                    except Exception as exc:
                        logger.warning(f"[MOVE] Failed to move symbol handle {entity_handle}: {exc}")
                self.sync_modelspace_entities()
                self.refresh_document()
                return
            for entity_handle in entry.get("entity_handles", []) or []:
                try:
                    logger.info(f"[MOVE] Moving entity {entity_handle} by vector {vector}")
                    self.doc.HandleToObject(entity_handle).Move(
                        to_variant_point((0.0, 0.0, 0.0)),
                        to_variant_point(vector)
                    )
                    logger.info(f"[MOVE] Entity {entity_handle} moved successfully")
                except Exception as exc:
                    logger.warning(f"[MOVE] Failed to move entity handle {entity_handle}: {exc}")
                self.sync_modelspace_entities()
                self.refresh_document()
                return
        try:
            entity = self.get_entity_by_handle(handle)
            logger.info(f"[MOVE] Moving unmanaged entity {handle} by vector {vector}")
            entity.Move(
                to_variant_point((0.0, 0.0, 0.0)),
                to_variant_point(vector)
            )
            logger.info(f"[MOVE] Unmanaged entity {handle} moved successfully")
            self.sync_modelspace_entities()
            self.refresh_document()
        except Exception as exc:
            logger.warning(f"[MOVE] Failed to move unmanaged entity {handle}: {exc}")

    def rotate_entity(self, handle: str, angle_degrees: float, base_point: Tuple[float, float, float] = (0.0, 0.0, 0.0)) -> None:
        if not self.is_connected():
            raise RuntimeError("AutoCAD is not connected")
        logical_handle = self.resolve_logical_handle(handle)
        if logical_handle != handle:
            self._log("ROTATE", f"Resolved primitive {handle} -> {logical_handle}")
        entry = self.entity_registry.get(logical_handle)
        rotation_radians = math.radians(angle_degrees)
        if entry:
            self._log("ROTATE", f"Rotating logical entity {logical_handle} type={entry.get('entity_type')} angle={angle_degrees}")
            entity_type = entry.get("entity_type")
            if entity_type == "pipe":
                for segment_handle in entry.get("segment_handles", []) or []:
                    try:
                        logger.info(f"[ROTATE] Rotating pipe segment {segment_handle} by {angle_degrees}° around {base_point}")
                        self.doc.HandleToObject(segment_handle).Rotate(
                            to_variant_point(base_point),
                            rotation_radians
                        )
                        logger.info(f"[ROTATE] Pipe segment {segment_handle} rotated successfully")
                    except Exception as exc:
                        logger.warning(f"[ROTATE] Failed to rotate pipe segment {segment_handle}: {exc}")
                self.sync_modelspace_entities()
                self.refresh_document()
                return
            if entity_type == "symbol":
                group_handle = entry.get("group_handle")
                if group_handle:
                    try:
                        logger.info(f"[ROTATE] Rotating symbol group {group_handle} by {angle_degrees}° around {base_point}")
                        self.doc.HandleToObject(group_handle).Rotate(
                            to_variant_point(base_point),
                            rotation_radians
                        )
                        logger.info(f"[ROTATE] Symbol group {group_handle} rotated successfully")
                        self.sync_modelspace_entities()
                        self.refresh_document()
                        return
                    except Exception as exc:
                        logger.warning(f"[ROTATE] Symbol group rotate failed: {exc}")
                for entity_handle in entry.get("entity_handles", []) or []:
                    try:
                        logger.info(f"[ROTATE] Rotating symbol entity {entity_handle} by {angle_degrees}° around {base_point}")
                        self.doc.HandleToObject(entity_handle).Rotate(
                            to_variant_point(base_point),
                            rotation_radians
                        )
                        logger.info(f"[ROTATE] Symbol entity {entity_handle} rotated successfully")
                    except Exception as exc:
                        logger.warning(f"[ROTATE] Failed to rotate symbol handle {entity_handle}: {exc}")
                self.sync_modelspace_entities()
                self.refresh_document()
                return
            for entity_handle in entry.get("entity_handles", []) or []:
                try:
                    logger.info(f"[ROTATE] Rotating entity {entity_handle} by {angle_degrees}° around {base_point}")
                    self.doc.HandleToObject(entity_handle).Rotate(
                        to_variant_point(base_point),
                        rotation_radians
                    )
                    logger.info(f"[ROTATE] Entity {entity_handle} rotated successfully")
                except Exception as exc:
                    logger.warning(f"[ROTATE] Failed to rotate entity handle {entity_handle}: {exc}")
                self.sync_modelspace_entities()
                self.refresh_document()
                return
        try:
            entity = self.get_entity_by_handle(handle)
            logger.info(f"[ROTATE] Rotating unmanaged entity {handle} by {angle_degrees}° around {base_point}")
            entity.Rotate(
                to_variant_point(base_point),
                rotation_radians
            )
            logger.info(f"[ROTATE] Unmanaged entity {handle} rotated successfully")
            self.sync_modelspace_entities()
            self.refresh_document()
        except Exception as exc:
            logger.warning(f"[ROTATE] Failed to rotate unmanaged entity {handle}: {exc}")

    def entity_metadata(self, entity) -> Dict[str, Any]:
        handle = self._handle_for(entity)
        if not handle:
            return self._extract_entity_metadata(entity)

        logical_handle = self.resolve_logical_handle(handle)
        if logical_handle in self.entity_registry:
            self._log("OWNERSHIP", f"Resolved metadata primitive {handle} -> {logical_handle}")
            return self.entity_registry[logical_handle]

        return self._extract_entity_metadata(entity)

    def count_entities(self) -> int:
        return len(self.entity_registry) if self.is_connected() else 0

    def modelspace_count(self) -> int:
        if not self.is_connected():
            return 0
        try:
            return int(self.modelspace.Count)
        except Exception:
            return 0

    def document_layers(self) -> List[str]:
        if not self.is_connected():
            return []
        return [self.doc.Layers.Item(i).Name for i in range(self.doc.Layers.Count)]

    def block_definitions(self) -> List[str]:
        if not self.is_connected():
            return []
        return [self.doc.Blocks.Item(i).Name for i in range(self.doc.Blocks.Count)]

    def insertion_point_for(self, entity) -> Tuple[float, float, float]:
        try:
            if hasattr(entity, "InsertionPoint"):
                insertion_raw = tuple(entity.InsertionPoint)
                if len(insertion_raw) >= 2:
                    return (
                        float(insertion_raw[0]),
                        float(insertion_raw[1]),
                        float(insertion_raw[2]) if len(insertion_raw) > 2 else 0.0,
                    )
        except Exception:
            pass

        handle = self._handle_for(entity) or str(getattr(entity, "Handle", ""))
        logical_handle = self.resolve_logical_handle(handle) if handle else handle
        entry = self.entity_registry.get(logical_handle) if logical_handle else None
        if entry:
            insertion = entry.get("insertion_point")
            if isinstance(insertion, (tuple, list)) and len(insertion) >= 2:
                return (
                    float(insertion[0]),
                    float(insertion[1]),
                    float(insertion[2]) if len(insertion) > 2 else 0.0,
                )
            recovered = self._recover_symbol_insertion_point(entry.get("entity_handles", []) or [])
            if recovered:
                return recovered
        return (0.0, 0.0, 0.0)

    def _entity_bounds(self, entity) -> Optional[Tuple[Point3D, Point3D]]:
        try:
            bounds = entity.GetBoundingBox()
            if not isinstance(bounds, tuple) or len(bounds) != 2:
                return None
            min_pt = self._to_point3d(bounds[0])
            max_pt = self._to_point3d(bounds[1])
            if not min_pt or not max_pt:
                return None
            return (min_pt, max_pt)
        except Exception:
            return None

    def _center_from_bounds(self, bounds: Tuple[Point3D, Point3D]) -> Point3D:
        min_pt, max_pt = bounds
        return (
            (float(min_pt[0]) + float(max_pt[0])) / 2.0,
            (float(min_pt[1]) + float(max_pt[1])) / 2.0,
            (float(min_pt[2]) + float(max_pt[2])) / 2.0,
        )

    def connection_point_for(self, entity) -> Point3D:
        handle = self._handle_for(entity) or str(getattr(entity, "Handle", ""))
        logical_handle = self.resolve_logical_handle(handle) if handle else handle
        entry = self.entity_registry.get(logical_handle) if logical_handle else None

        # For logical symbols, compute center from combined primitive bounding box.
        if entry and entry.get("entity_type") == "symbol":
            min_x = min_y = min_z = None
            max_x = max_y = max_z = None
            for raw_handle in entry.get("entity_handles", []) or []:
                hs = str(raw_handle).strip()
                if not self._looks_like_raw_autocad_handle(hs):
                    continue
                try:
                    raw_entity = self.doc.HandleToObject(hs)
                    raw_bounds = self._entity_bounds(raw_entity)
                    if not raw_bounds:
                        continue
                    raw_min, raw_max = raw_bounds
                    min_x = raw_min[0] if min_x is None else min(min_x, raw_min[0])
                    min_y = raw_min[1] if min_y is None else min(min_y, raw_min[1])
                    min_z = raw_min[2] if min_z is None else min(min_z, raw_min[2])
                    max_x = raw_max[0] if max_x is None else max(max_x, raw_max[0])
                    max_y = raw_max[1] if max_y is None else max(max_y, raw_max[1])
                    max_z = raw_max[2] if max_z is None else max(max_z, raw_max[2])
                except Exception:
                    continue
            if min_x is not None and max_x is not None:
                return (
                    (float(min_x) + float(max_x)) / 2.0,
                    (float(min_y) + float(max_y)) / 2.0,
                    (float(min_z) + float(max_z)) / 2.0,
                )

        # For single entities, use their own bounds center when available.
        direct_bounds = self._entity_bounds(entity)
        if direct_bounds:
            return self._center_from_bounds(direct_bounds)

        return self.insertion_point_for(entity)
