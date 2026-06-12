"""
JSON -> Graph -> Geometry -> DXF exporter for P&ID data.

This module is deterministic and extensible:
- Parsing and validation are isolated in PidJsonParser
- Symbol-to-geometry mapping is isolated in EquipmentShapeMapper
- CAD generation is isolated in PidDxfExporter

Example:
    python pid_to_dxf.py --input pid_graph.json --output output.dxf
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Set, Tuple

import ezdxf

Point2D = Tuple[float, float]
EquipmentDrawer = Callable[[ezdxf.layouts.Modelspace, "EquipmentNode", float], None]

LAYER_EQUIPMENT = "EQUIPMENT"
LAYER_PIPES = "PIPES"
LAYER_PIPES_DASHED = "PIPES_DASHED"
LAYER_LABELS = "LABELS"

# Default drawing scale tuned for backend graph coordinates from the Digi P&ID pipeline.
DEFAULT_SYMBOL_SIZE = 18.0
DEFAULT_TEXT_HEIGHT = 3.5


class SchemaValidationError(ValueError):
    """Raised when the input JSON does not match supported schema."""


@dataclass(frozen=True)
class EquipmentNode:
    node_id: str
    node_type: str
    position: Point2D
    label: str | None = None
    symbol_width: float | None = None
    symbol_height: float | None = None


@dataclass(frozen=True)
class PipeEdge:
    source_id: str
    target_id: str


@dataclass(frozen=True)
class Junction:
    junction_id: str
    position: Point2D
    connected_nodes: Tuple[str, ...]


@dataclass(frozen=True)
class PidGraph:
    equipment: Tuple[EquipmentNode, ...]
    pipes: Tuple[PipeEdge, ...]

    @property
    def positions_by_id(self) -> Dict[str, Point2D]:
        return {node.node_id: node.position for node in self.equipment}


class PidJsonParser:
    """
    Parses JSON payload into canonical PidGraph.

    Supported input formats:
    1) Canonical:
        {
          "equipment": [{"id": "P1", "type": "pump", "position": [0, 0]}],
          "pipes": [{"from": "P1", "to": "V1"}]
        }
    2) Existing backend graph list:
        [{"node_id": 1, "type": "...", "bbox": [...], "connections": [...]}]
    3) Existing backend response:
        {"graph_data": {"json": [ ...same as #2... ]}}
    """

    def parse(self, payload: Mapping[str, object]) -> PidGraph:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("Root JSON object must be a mapping/object.")

        if "equipment" in payload and "pipes" in payload:
            return self._parse_canonical(payload)

        if "graph_data" in payload:
            graph_data = payload.get("graph_data")
            if isinstance(graph_data, Mapping) and isinstance(graph_data.get("json"), list):
                return self._parse_backend_graph_nodes(graph_data["json"])

        if isinstance(payload.get("json"), list):
            return self._parse_backend_graph_nodes(payload["json"])

        raise SchemaValidationError(
            "Unsupported schema. Expected canonical {equipment,pipes} or backend graph_data.json list."
        )

    def _parse_canonical(self, payload: Mapping[str, object]) -> PidGraph:
        raw_equipment = payload.get("equipment")
        raw_pipes = payload.get("pipes")

        if not isinstance(raw_equipment, list):
            raise SchemaValidationError("'equipment' must be a list.")
        if not isinstance(raw_pipes, list):
            raise SchemaValidationError("'pipes' must be a list.")

        equipment_nodes = []
        for idx, item in enumerate(raw_equipment):
            if not isinstance(item, Mapping):
                raise SchemaValidationError(f"equipment[{idx}] must be an object.")
            node_id = str(item.get("id", "")).strip()
            node_type = str(item.get("type", "")).strip().lower()
            position = item.get("position")
            if not node_id:
                raise SchemaValidationError(f"equipment[{idx}].id is required.")
            if not node_type:
                raise SchemaValidationError(f"equipment[{idx}].type is required.")
            x, y = self._validate_position(position, f"equipment[{idx}].position")
            label = item.get("label")
            equipment_nodes.append(
                EquipmentNode(node_id=node_id, node_type=node_type, position=(x, y), label=str(label) if label else None)
            )

        equipment_by_id = {node.node_id: node for node in equipment_nodes}
        if len(equipment_by_id) != len(equipment_nodes):
            raise SchemaValidationError("Duplicate equipment ids detected.")

        dedup_pipes = set()
        pipes = []
        for idx, item in enumerate(raw_pipes):
            if not isinstance(item, Mapping):
                raise SchemaValidationError(f"pipes[{idx}] must be an object.")
            source_id = str(item.get("from", "")).strip()
            target_id = str(item.get("to", "")).strip()
            if not source_id or not target_id:
                raise SchemaValidationError(f"pipes[{idx}] requires 'from' and 'to'.")
            if source_id not in equipment_by_id or target_id not in equipment_by_id:
                raise SchemaValidationError(f"pipes[{idx}] references unknown equipment id(s).")
            if source_id == target_id:
                continue
            edge_key = tuple(sorted((source_id, target_id)))
            if edge_key in dedup_pipes:
                continue
            dedup_pipes.add(edge_key)
            pipes.append(PipeEdge(source_id=edge_key[0], target_id=edge_key[1]))

        ordered_equipment = tuple(sorted(equipment_nodes, key=lambda n: n.node_id))
        ordered_pipes = tuple(sorted(pipes, key=lambda e: (e.source_id, e.target_id)))
        return PidGraph(equipment=ordered_equipment, pipes=ordered_pipes)

    def _parse_backend_graph_nodes(self, rows: object) -> PidGraph:
        if not isinstance(rows, list):
            raise SchemaValidationError("Backend graph nodes must be a list.")

        equipment_nodes = []
        for idx, item in enumerate(rows):
            if not isinstance(item, Mapping):
                raise SchemaValidationError(f"graph node[{idx}] must be an object.")
            node_id = str(item.get("id", item.get("node_id", ""))).strip()
            node_type = str(item.get("type", "unknown")).strip().lower()
            if not node_id:
                raise SchemaValidationError(f"graph node[{idx}] missing node id.")
            position = self._extract_backend_position(item, idx)
            label = item.get("tag")
            equipment_nodes.append(
                EquipmentNode(node_id=node_id, node_type=node_type, position=position, label=str(label) if label else None)
            )

        equipment_by_id = {node.node_id: node for node in equipment_nodes}
        if len(equipment_by_id) != len(equipment_nodes):
            raise SchemaValidationError("Duplicate graph node ids detected.")

        dedup_pipes = set()
        pipes = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            source_id = str(item.get("id", item.get("node_id", ""))).strip()
            raw_connections = item.get("connections", [])
            if not isinstance(raw_connections, list):
                continue
            for raw_target in raw_connections:
                target_id = str(raw_target).strip()
                if not source_id or not target_id:
                    continue
                if source_id not in equipment_by_id or target_id not in equipment_by_id:
                    continue
                if source_id == target_id:
                    continue
                edge_key = tuple(sorted((source_id, target_id)))
                if edge_key in dedup_pipes:
                    continue
                dedup_pipes.add(edge_key)
                pipes.append(PipeEdge(source_id=edge_key[0], target_id=edge_key[1]))

        ordered_equipment = tuple(sorted(equipment_nodes, key=lambda n: n.node_id))
        ordered_pipes = tuple(sorted(pipes, key=lambda e: (e.source_id, e.target_id)))
        return PidGraph(equipment=ordered_equipment, pipes=ordered_pipes)

    @staticmethod
    def _validate_position(position: object, field_name: str) -> Point2D:
        if not isinstance(position, (list, tuple)) or len(position) != 2:
            raise SchemaValidationError(f"{field_name} must be [x, y].")
        try:
            return float(position[0]), float(position[1])
        except (TypeError, ValueError) as exc:
            raise SchemaValidationError(f"{field_name} must contain numeric coordinates.") from exc

    @staticmethod
    def _extract_backend_position(item: Mapping[str, object], row_idx: int) -> Point2D:
        if "position" in item:
            return PidJsonParser._validate_position(item["position"], f"graph node[{row_idx}].position")
        if "coords" in item:
            return PidJsonParser._validate_position(item["coords"], f"graph node[{row_idx}].coords")

        bbox = item.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                x1, y1, x2, y2 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
                return (x1 + x2) / 2.0, (y1 + y2) / 2.0
            except (TypeError, ValueError):
                pass

        raise SchemaValidationError(
            f"graph node[{row_idx}] requires one of: position, coords, or numeric bbox."
        )


class EquipmentShapeMapper:
    """
    Central symbol mapping layer.

    Why this exists:
    - Keeps geometric rules separate from parsing and DXF orchestration.
    - Makes future symbol extension deterministic and low-risk.
    """

    def __init__(self) -> None:
        self._drawers: Dict[str, EquipmentDrawer] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register("pump", self._draw_pump)
        self.register("valve", self._draw_valve)
        self.register("*", self._draw_default)

    def register(self, equipment_type: str, drawer: EquipmentDrawer) -> None:
        self._drawers[equipment_type.lower()] = drawer

    def draw(self, msp: ezdxf.layouts.Modelspace, node: EquipmentNode, symbol_size: float) -> None:
        drawer = self._drawers.get(node.node_type, self._drawers["*"])
        drawer(msp, node, symbol_size)

    @staticmethod
    def _draw_pump(msp: ezdxf.layouts.Modelspace, node: EquipmentNode, symbol_size: float) -> None:
        x, y = node.position
        msp.add_circle((x, y), radius=symbol_size * 0.5, dxfattribs={"layer": LAYER_EQUIPMENT})

    @staticmethod
    def _draw_valve(msp: ezdxf.layouts.Modelspace, node: EquipmentNode, symbol_size: float) -> None:
        x, y = node.position
        h = symbol_size * 0.55
        points = [(x, y + h), (x + h, y), (x, y - h), (x - h, y)]
        msp.add_lwpolyline(points, close=True, dxfattribs={"layer": LAYER_EQUIPMENT})

    @staticmethod
    def _draw_default(msp: ezdxf.layouts.Modelspace, node: EquipmentNode, symbol_size: float) -> None:
        x, y = node.position
        h = symbol_size * 0.5
        points = [(x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h)]
        msp.add_lwpolyline(points, close=True, dxfattribs={"layer": LAYER_EQUIPMENT})


class TemplateDrivenShapeMapper(EquipmentShapeMapper):
    """
    Template-driven symbol mapper.

    Uses symbol_templates.json when available and falls back to default square
    rendering for missing/invalid templates.
    """

    def __init__(self, template_path: str | Path = "symbol_templates.json") -> None:
        super().__init__()
        self.templates: Dict[str, object] = {}

        raw_path = Path(template_path)
        candidate_paths = [raw_path]
        if not raw_path.is_absolute():
            candidate_paths.append(Path(__file__).resolve().parent / raw_path)

        for path in candidate_paths:
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.templates = loaded
                    break
            except Exception:
                self.templates = {}

    def draw(self, msp: ezdxf.layouts.Modelspace, node: EquipmentNode, symbol_size: float) -> None:
        template = self._get_template(node.node_type)
        if not template:
            self._draw_fallback(msp, node, symbol_size)
            return

        primitives = template.get("primitives", {}) if isinstance(template, Mapping) else {}
        lines = primitives.get("lines", []) if isinstance(primitives, Mapping) else []
        circles = primitives.get("circles", []) if isinstance(primitives, Mapping) else []
        contours = primitives.get("contours", []) if isinstance(primitives, Mapping) else []
        fill = template.get("fill", {}) if isinstance(template, Mapping) else {}
        texts = template.get("texts", []) if isinstance(template, Mapping) else []
        if (not isinstance(texts, list) or len(texts) == 0) and isinstance(primitives, Mapping):
            texts = primitives.get("texts", [])
        if not isinstance(texts, list):
            texts = []
        if not isinstance(fill, Mapping):
            fill = {}

        if not lines and not circles and not contours and not texts:
            self._draw_fallback(msp, node, symbol_size)
            return

        cx, cy = node.position
        target_w = float(node.symbol_width) if node.symbol_width and node.symbol_width > 0 else float(symbol_size)
        target_h = float(node.symbol_height) if node.symbol_height and node.symbol_height > 0 else float(symbol_size)

        # Compute template bounds in local coordinates so symbols can fill YOLO bbox proportionally.
        local_points: List[Point2D] = []

        if isinstance(contours, list):
            for contour in contours:
                if not isinstance(contour, list):
                    continue
                for pt in contour:
                    if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                        continue
                    try:
                        lx, ly = self._normalize_point_to_local(float(pt[0]), float(pt[1]))
                    except (TypeError, ValueError):
                        continue
                    local_points.append((lx, ly))

        if isinstance(lines, list):
            for line in lines:
                if not isinstance(line, (list, tuple)) or len(line) != 4:
                    continue
                try:
                    x1, y1, x2, y2 = map(float, line)
                except (TypeError, ValueError):
                    continue
                local_points.append(self._normalize_point_to_local(x1, y1))
                local_points.append(self._normalize_point_to_local(x2, y2))

        if isinstance(circles, list):
            for circ in circles:
                if not isinstance(circ, (list, tuple)) or len(circ) != 3:
                    continue
                try:
                    x, y, r = map(float, circ)
                except (TypeError, ValueError):
                    continue
                lx, ly, lr = self._normalize_circle_to_local(x, y, r)
                local_points.append((lx - lr, ly - lr))
                local_points.append((lx + lr, ly + lr))

        if local_points:
            xs = [p[0] for p in local_points]
            ys = [p[1] for p in local_points]
            local_w = max(1e-6, max(xs) - min(xs))
            local_h = max(1e-6, max(ys) - min(ys))
            scale_x = (target_w * 0.92) / local_w
            scale_y = (target_h * 0.92) / local_h

            # Prefer near-uniform scaling to preserve instrument proportions.
            ratio = max(scale_x, scale_y) / max(1e-6, min(scale_x, scale_y))
            if ratio <= 1.25:
                uniform = (scale_x + scale_y) * 0.5
                scale_x = uniform
                scale_y = uniform
        else:
            base_scale = float(symbol_size) / 100.0
            scale_x = base_scale
            scale_y = base_scale

        angle = float(getattr(node, "orientation", 0.0) or 0.0)
        theta = math.radians(angle)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        def rotate(x: float, y: float) -> Point2D:
            return (
                x * cos_t - y * sin_t,
                x * sin_t + y * cos_t,
            )

        drawn = False
        contour_fills = fill.get("contours", [])
        circle_fills = fill.get("circles", [])

        transformed_contours: List[Tuple[List[Point2D], str]] = []
        for i, contour in enumerate(contours if isinstance(contours, list) else []):
            if not isinstance(contour, list) or len(contour) < 3:
                continue
            pts: List[Point2D] = []
            raw_xs: List[float] = []
            raw_ys: List[float] = []
            for pt in contour:
                if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                    continue
                try:
                    px, py = float(pt[0]), float(pt[1])
                except (TypeError, ValueError):
                    continue
                raw_xs.append(px)
                raw_ys.append(py)
                px, py = self._normalize_point_to_local(px, py)
                px *= scale_x
                py *= scale_y
                rpx, rpy = rotate(px, py)
                pts.append((cx + rpx, cy + rpy))
            if len(pts) < 3:
                continue

            # Skip contour artifacts that are just the ROI frame/border.
            if raw_xs and raw_ys:
                min_x, max_x = min(raw_xs), max(raw_xs)
                min_y, max_y = min(raw_ys), max(raw_ys)
                is_norm = 0.0 <= min_x <= 1.0 and 0.0 <= max_x <= 1.0 and 0.0 <= min_y <= 1.0 and 0.0 <= max_y <= 1.0
                is_px = 0.0 <= min_x <= 150.0 and 0.0 <= max_x <= 150.0 and 0.0 <= min_y <= 150.0 and 0.0 <= max_y <= 150.0
                if is_norm:
                    touches_frame = (min_x <= 0.03 and max_x >= 0.97 and min_y <= 0.03 and max_y >= 0.97)
                    if touches_frame:
                        continue
                elif is_px:
                    touches_frame = (min_x <= 3.0 and max_x >= 125.0 and min_y <= 3.0 and max_y >= 125.0)
                    if touches_frame:
                        continue

            fill_mode = "none"
            if isinstance(contour_fills, list) and i < len(contour_fills):
                fill_mode = str(contour_fills[i]).strip().lower()
            transformed_contours.append((pts, fill_mode))

        transformed_circles: List[Tuple[Point2D, float, str]] = []
        for i, circ in enumerate(circles if isinstance(circles, list) else []):
            if not isinstance(circ, (list, tuple)) or len(circ) != 3:
                continue
            try:
                x, y, r = map(float, circ)
            except (TypeError, ValueError):
                continue
            x, y, r = self._normalize_circle_to_local(x, y, r)
            x *= scale_x
            y *= scale_y
            r *= min(scale_x, scale_y)
            if r <= 0.0:
                continue
            rx, ry = rotate(x, y)
            fill_mode = "none"
            if isinstance(circle_fills, list) and i < len(circle_fills):
                fill_mode = str(circle_fills[i]).strip().lower()
            transformed_circles.append(((cx + rx, cy + ry), r, fill_mode))

        # 1) Filled contours
        for pts, fill_mode in transformed_contours:
            if fill_mode != "filled":
                continue
            try:
                hatch = msp.add_hatch(color=7, dxfattribs={"layer": LAYER_EQUIPMENT, "color": 7})
                hatch.paths.add_polyline_path(pts, is_closed=True)
                drawn = True
            except Exception:
                continue

        # 2) Filled circles
        for center, r, fill_mode in transformed_circles:
            if fill_mode != "filled":
                continue
            try:
                hatch = msp.add_hatch(color=7, dxfattribs={"layer": LAYER_EQUIPMENT, "color": 7})
                edge = hatch.paths.add_edge_path()
                edge.add_arc(center=center, radius=r, start_angle=0.0, end_angle=360.0)
                drawn = True
            except Exception:
                continue

        # 3) Outlines
        for pts, _ in transformed_contours:
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": LAYER_EQUIPMENT, "color": 7})
            drawn = True

        for center, r, _ in transformed_circles:
            msp.add_circle(center, r, dxfattribs={"layer": LAYER_EQUIPMENT, "color": 7})
            drawn = True

        # 4) Lines
        for line in lines if isinstance(lines, list) else []:
            if not isinstance(line, (list, tuple)) or len(line) != 4:
                continue
            try:
                x1, y1, x2, y2 = map(float, line)
            except (TypeError, ValueError):
                continue

            # Skip line artifacts that are likely ROI frame edges.
            if 0.0 <= x1 <= 1.0 and 0.0 <= y1 <= 1.0 and 0.0 <= x2 <= 1.0 and 0.0 <= y2 <= 1.0:
                near_top = y1 <= 0.04 and y2 <= 0.04 and min(x1, x2) <= 0.03 and max(x1, x2) >= 0.97
                near_bottom = y1 >= 0.96 and y2 >= 0.96 and min(x1, x2) <= 0.03 and max(x1, x2) >= 0.97
                near_left = x1 <= 0.04 and x2 <= 0.04 and min(y1, y2) <= 0.03 and max(y1, y2) >= 0.97
                near_right = x1 >= 0.96 and x2 >= 0.96 and min(y1, y2) <= 0.03 and max(y1, y2) >= 0.97
                if near_top or near_bottom or near_left or near_right:
                    continue
            elif 0.0 <= x1 <= 150.0 and 0.0 <= y1 <= 150.0 and 0.0 <= x2 <= 150.0 and 0.0 <= y2 <= 150.0:
                near_top = y1 <= 4.0 and y2 <= 4.0 and min(x1, x2) <= 3.0 and max(x1, x2) >= 125.0
                near_bottom = y1 >= 124.0 and y2 >= 124.0 and min(x1, x2) <= 3.0 and max(x1, x2) >= 125.0
                near_left = x1 <= 4.0 and x2 <= 4.0 and min(y1, y2) <= 3.0 and max(y1, y2) >= 125.0
                near_right = x1 >= 124.0 and x2 >= 124.0 and min(y1, y2) <= 3.0 and max(y1, y2) >= 125.0
                if near_top or near_bottom or near_left or near_right:
                    continue

            x1, y1 = self._normalize_point_to_local(x1, y1)
            x2, y2 = self._normalize_point_to_local(x2, y2)

            x1 *= scale_x
            y1 *= scale_y
            x2 *= scale_x
            y2 *= scale_y

            rx1, ry1 = rotate(x1, y1)
            rx2, ry2 = rotate(x2, y2)
            msp.add_line(
                (cx + rx1, cy + ry1),
                (cx + rx2, cy + ry2),
                dxfattribs={"layer": LAYER_EQUIPMENT, "color": 7},
            )
            drawn = True

        # 5) Texts on top
        # Keep template text compact relative to symbol size.
        base_text_height = max(0.55, min(12.0, float(symbol_size) * 0.10))
        for txt in texts:
            if not isinstance(txt, (list, tuple)) or len(txt) != 4:
                continue
            try:
                tx, ty, content, scale_txt = txt
                tx = float(tx)
                ty = float(ty)
                content = str(content)
                scale_txt = float(scale_txt)
            except Exception:
                continue
            if not content or scale_txt <= 0.0:
                continue

            tx, ty = self._normalize_point_to_local(tx, ty)
            tx *= scale_x
            ty *= scale_y
            rtx, rty = rotate(tx, ty)
            x_pos = cx + rtx
            y_pos = cy + rty

            try:
                effective_scale = scale_txt
                if effective_scale <= 1.0:
                    effective_scale = max(0.30, effective_scale * 3.8)
                text_entity = msp.add_text(
                    content,
                    dxfattribs={
                        "height": max(0.01, base_text_height * effective_scale),
                        "layer": LAYER_LABELS,
                        "color": 7,
                    },
                )
                text_entity.set_placement((x_pos, y_pos))
                drawn = True
            except Exception:
                continue

        if not drawn:
            self._draw_fallback(msp, node, symbol_size)

    def _get_template(self, node_type: str) -> Mapping[str, object] | None:
        if not self.templates:
            return None
        key = str(node_type or "").strip().lower()
        if not key:
            return None
        template = self.templates.get(key)
        if isinstance(template, Mapping):
            return template
        # Case-insensitive fallback lookup.
        for k, v in self.templates.items():
            if str(k).strip().lower() == key and isinstance(v, Mapping):
                return v
        return None

    @staticmethod
    def _normalize_point_to_local(x: float, y: float) -> Point2D:
        # Normalized [0..1] format.
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
            return (x - 0.5) * 100.0, (0.5 - y) * 100.0
        # Pixel-like [0..128] format.
        if 0.0 <= x <= 150.0 and 0.0 <= y <= 150.0:
            return ((x / 128.0) - 0.5) * 100.0, (0.5 - (y / 128.0)) * 100.0
        # Already local.
        return x, y

    @staticmethod
    def _normalize_circle_to_local(x: float, y: float, r: float) -> Tuple[float, float, float]:
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 <= r <= 1.0:
            lx, ly = TemplateDrivenShapeMapper._normalize_point_to_local(x, y)
            return lx, ly, r * 100.0
        if 0.0 <= x <= 150.0 and 0.0 <= y <= 150.0 and 0.0 <= r <= 80.0:
            lx, ly = TemplateDrivenShapeMapper._normalize_point_to_local(x, y)
            return lx, ly, (r / 128.0) * 100.0
        return x, y, r

    @staticmethod
    def _draw_fallback(msp: ezdxf.layouts.Modelspace, node: EquipmentNode, symbol_size: float) -> None:
        x, y = node.position
        fallback_w = float(node.symbol_width) if node.symbol_width and node.symbol_width > 0 else float(symbol_size)
        fallback_h = float(node.symbol_height) if node.symbol_height and node.symbol_height > 0 else float(symbol_size)
        hx = fallback_w * 0.5
        hy = fallback_h * 0.5
        msp.add_lwpolyline(
            [(x - hx, y - hy), (x + hx, y - hy), (x + hx, y + hy), (x - hx, y + hy)],
            close=True,
            dxfattribs={"layer": LAYER_EQUIPMENT},
        )


class PidDxfExporter:
    """Draws canonical PidGraph into a DXF modelspace."""

    def __init__(
        self,
        mapper: EquipmentShapeMapper | None = None,
        symbol_size: float = DEFAULT_SYMBOL_SIZE,
        text_height: float = DEFAULT_TEXT_HEIGHT,
    ) -> None:
        self.mapper = mapper or TemplateDrivenShapeMapper("symbol_templates.json")
        self.symbol_size = float(symbol_size)
        self.text_height = float(text_height)

    def export(self, graph: PidGraph, output_path: str | Path) -> Path:
        if not graph.equipment:
            raise SchemaValidationError("Graph has no equipment nodes to draw.")

        doc = ezdxf.new(dxfversion="R2018")
        self._ensure_layers(doc)
        msp = doc.modelspace()

        self._draw_equipment(msp, graph.equipment)
        self._draw_pipes(msp, graph.pipes, graph.positions_by_id)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(output_path)
        return output_path

    @staticmethod
    def _ensure_layers(doc: ezdxf.EzDxf) -> None:
        if "DASHED" not in doc.linetypes:
            try:
                doc.linetypes.new(
                    "DASHED",
                    dxfattribs={
                        "description": "Dashed __ __ __",
                        "pattern": [0.6, 0.3, -0.3],
                    },
                )
            except Exception:
                # Keep export resilient even if custom linetype creation fails.
                pass

        layer_specs = {
            LAYER_EQUIPMENT: 3,
            LAYER_PIPES: 1,
            LAYER_PIPES_DASHED: 5,
            LAYER_LABELS: 7,
        }
        for layer_name, color in layer_specs.items():
            if layer_name not in doc.layers:
                dxfattribs = {"color": color}
                if layer_name == LAYER_PIPES_DASHED and "DASHED" in doc.linetypes:
                    dxfattribs["linetype"] = "DASHED"
                doc.layers.add(name=layer_name, dxfattribs=dxfattribs)

    def _draw_equipment(self, msp: ezdxf.layouts.Modelspace, equipment: Iterable[EquipmentNode]) -> None:
        for node in sorted(equipment, key=lambda n: n.node_id):
            self.mapper.draw(msp, node, self.symbol_size)
            label_text = node.label if node.label else f"{node.node_id} ({node.node_type})"
            text = msp.add_text(
                label_text,
                dxfattribs={"height": self.text_height, "layer": LAYER_LABELS},
            )
            text.set_placement((node.position[0] + self.symbol_size * 0.8, node.position[1] + self.symbol_size * 0.2))

    def _draw_pipes(
        self,
        msp: ezdxf.layouts.Modelspace,
        pipes: Iterable[PipeEdge],
        positions_by_id: Mapping[str, Point2D],
    ) -> None:
        adjacency = self._build_adjacency(pipes)
        junctions_by_node = self._detect_junctions(adjacency, positions_by_id, self.symbol_size)
        routed_edges = self._build_routed_edges(pipes, junctions_by_node)

        anchor_positions: Dict[str, Point2D] = dict(positions_by_id)
        for junction in junctions_by_node.values():
            anchor_positions[junction.junction_id] = junction.position

        junction_ids = {junction.junction_id for junction in junctions_by_node.values()}
        junction_radius = max(2.0, self.symbol_size * 0.2)

        for left_id, right_id in sorted(routed_edges):
            start_center = anchor_positions[left_id]
            end_center = anchor_positions[right_id]

            start_offset = self._get_port_offset(left_id, junction_ids, self.symbol_size, junction_radius)
            end_offset = self._get_port_offset(right_id, junction_ids, self.symbol_size, junction_radius)

            start_port = self._get_port_position(start_center, end_center, start_offset)
            end_port = self._get_port_position(end_center, start_center, end_offset)

            route = self._route_pipe(start_port, end_port)
            if len(route) >= 2:
                msp.add_lwpolyline(route, dxfattribs={"layer": LAYER_PIPES})

        for junction in sorted(junctions_by_node.values(), key=lambda j: j.junction_id):
            msp.add_circle(center=junction.position, radius=junction_radius, dxfattribs={"layer": LAYER_PIPES})

    @staticmethod
    def _build_adjacency(pipes: Iterable[PipeEdge]) -> Dict[str, Set[str]]:
        adjacency: Dict[str, Set[str]] = {}
        for edge in pipes:
            adjacency.setdefault(edge.source_id, set()).add(edge.target_id)
            adjacency.setdefault(edge.target_id, set()).add(edge.source_id)
        return adjacency

    @staticmethod
    def _detect_junctions(
        adjacency: Mapping[str, Set[str]],
        positions_by_id: Mapping[str, Point2D],
        symbol_size: float,
    ) -> Dict[str, Junction]:
        junctions: Dict[str, Junction] = {}
        offset = max(symbol_size * 1.5, 8.0)

        for node_id in sorted(adjacency.keys()):
            neighbors = sorted(adjacency[node_id])
            if len(neighbors) <= 2 or node_id not in positions_by_id:
                continue

            center = positions_by_id[node_id]
            neighbor_positions = [positions_by_id[nid] for nid in neighbors if nid in positions_by_id]
            junction_position = PidDxfExporter._compute_virtual_junction_position(center, neighbor_positions, offset)

            junctions[node_id] = Junction(
                junction_id=f"J:{node_id}",
                position=junction_position,
                connected_nodes=tuple(neighbors),
            )

        return junctions

    @staticmethod
    def _compute_virtual_junction_position(
        center: Point2D,
        neighbor_positions: List[Point2D],
        offset: float,
    ) -> Point2D:
        x, y = center
        if not neighbor_positions:
            return x + offset, y

        dx = sum((nx - x) for nx, _ in neighbor_positions) / len(neighbor_positions)
        dy = sum((ny - y) for _, ny in neighbor_positions) / len(neighbor_positions)

        if abs(dx) >= abs(dy):
            return x + (offset if dx >= 0 else -offset), y
        return x, y + (offset if dy >= 0 else -offset)

    @staticmethod
    def _build_routed_edges(
        pipes: Iterable[PipeEdge],
        junctions_by_node: Mapping[str, Junction],
    ) -> Set[Tuple[str, str]]:
        routed_edges: Set[Tuple[str, str]] = set()

        def add_edge(a: str, b: str) -> None:
            if not a or not b or a == b:
                return
            routed_edges.add(tuple(sorted((a, b))))

        for edge in pipes:
            source_is_hub = edge.source_id in junctions_by_node
            target_is_hub = edge.target_id in junctions_by_node

            source_anchor = junctions_by_node[edge.source_id].junction_id if source_is_hub else edge.source_id
            target_anchor = junctions_by_node[edge.target_id].junction_id if target_is_hub else edge.target_id

            add_edge(source_anchor, target_anchor)
            if source_is_hub:
                add_edge(edge.source_id, source_anchor)
            if target_is_hub:
                add_edge(edge.target_id, target_anchor)

        return routed_edges

    @staticmethod
    def _get_port_position(center: Point2D, target: Point2D, port_offset: float) -> Point2D:
        x1, y1 = center
        x2, y2 = target
        if abs(x2 - x1) > abs(y2 - y1):
            return (x1 + port_offset if x2 > x1 else x1 - port_offset, y1)
        return (x1, y1 + port_offset if y2 > y1 else y1 - port_offset)

    @staticmethod
    def _get_port_offset(
        anchor_id: str,
        junction_ids: Set[str],
        symbol_size: float,
        junction_radius: float,
    ) -> float:
        if anchor_id in junction_ids:
            return junction_radius
        return max(symbol_size * 0.6, 3.0)

    @staticmethod
    def _route_pipe(start: Point2D, end: Point2D) -> List[Point2D]:
        x1, y1 = start
        x2, y2 = end
        mid_x = (x1 + x2) / 2.0
        raw_route: List[Point2D] = [
            (x1, y1),
            (mid_x, y1),
            (mid_x, y2),
            (x2, y2),
        ]

        # Remove duplicated consecutive points to avoid zero-length polyline segments.
        deduped: List[Point2D] = []
        for point in raw_route:
            if deduped and abs(deduped[-1][0] - point[0]) < 1e-9 and abs(deduped[-1][1] - point[1]) < 1e-9:
                continue
            deduped.append(point)
        return deduped


def export_pid_json_to_dxf(
    payload: Mapping[str, object],
    output_path: str | Path,
    symbol_size: float = DEFAULT_SYMBOL_SIZE,
    text_height: float = DEFAULT_TEXT_HEIGHT,
) -> Path:
    parser = PidJsonParser()
    graph = parser.parse(payload)
    mapper = TemplateDrivenShapeMapper("symbol_templates.json")
    exporter = PidDxfExporter(mapper=mapper, symbol_size=symbol_size, text_height=text_height)
    return exporter.export(graph=graph, output_path=output_path)


def _safe_point2d(value: object) -> Point2D | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None


def export_geometry_to_dxf(
    payload: Mapping[str, object],
    output_path: str | Path,
    symbol_radius: float = 10.0,
    text_height: float = 3.0,
    template_path: str | Path = "symbol_templates.json",
) -> Path:
    """
    Export geometry-first payload directly to DXF.

    Expected shape:
      {
        "equipment": [{"id": "...", "position": [x, y], "label": "..."}],
        "pipes": [{"id": "...", "points": [[x1, y1], [x2, y2], ...]}]
      }
    """
    if not isinstance(payload, Mapping):
        raise SchemaValidationError("Geometry payload root must be an object.")

    raw_equipment = payload.get("equipment", [])
    raw_pipes = payload.get("pipes", [])

    if not isinstance(raw_equipment, list):
        raise SchemaValidationError("'equipment' must be a list in geometry payload.")
    if not isinstance(raw_pipes, list):
        raise SchemaValidationError("'pipes' must be a list in geometry payload.")

    doc = ezdxf.new(dxfversion="R2018")
    PidDxfExporter._ensure_layers(doc)
    msp = doc.modelspace()

    # Draw pipes directly from geometry points.
    seen_pipe_keys = set()
    for pipe in raw_pipes:
        if not isinstance(pipe, Mapping):
            continue
        raw_points = pipe.get("points", [])
        if not isinstance(raw_points, list):
            continue
        raw_line_style = str(pipe.get("line_style", pipe.get("line_type", "solid"))).strip().lower()
        is_dashed = raw_line_style in {"dashed", "dotted", "dash", "dot", "instrument"}

        points: List[Point2D] = []
        for raw_pt in raw_points:
            pt = _safe_point2d(raw_pt)
            if pt is None:
                continue
            if points and abs(points[-1][0] - pt[0]) < 1e-9 and abs(points[-1][1] - pt[1]) < 1e-9:
                continue
            points.append(pt)

        if len(points) < 2:
            continue

        # Ignore zero-length polyline.
        if all(abs(points[i][0] - points[0][0]) < 1e-9 and abs(points[i][1] - points[0][1]) < 1e-9 for i in range(1, len(points))):
            continue

        # Deduplicate same/reversed geometry.
        rounded = tuple((round(p[0], 3), round(p[1], 3)) for p in points)
        rounded_rev = tuple(reversed(rounded))
        pipe_key = rounded if rounded <= rounded_rev else rounded_rev
        if pipe_key in seen_pipe_keys:
            continue
        seen_pipe_keys.add(pipe_key)

        dxfattribs = {"layer": LAYER_PIPES_DASHED if is_dashed else LAYER_PIPES}
        if is_dashed and "DASHED" in doc.linetypes:
            dxfattribs["linetype"] = "DASHED"
        msp.add_lwpolyline(points, dxfattribs=dxfattribs)

    # Draw equipment symbols and labels.
    # Use template-driven mapping here so geometry-direct export renders real
    # instrument shapes instead of generic circles.
    mapper = TemplateDrivenShapeMapper(template_path)
    # Geometry payload coordinates are in source-image scale, so a larger
    # symbol size is needed than the legacy circle radius to make templates
    # readable in CAD.
    base_symbol_size = max(36.0, float(symbol_radius) * 6.0)
    seen_equipment = set()
    for idx, eq in enumerate(raw_equipment, start=1):
        if not isinstance(eq, Mapping):
            continue
        eq_id = str(eq.get("id", "")).strip()
        if eq_id and eq_id in seen_equipment:
            continue

        position = _safe_point2d(eq.get("position"))
        if position is None:
            continue

        node_type = str(eq.get("type", "unknown")).strip().lower() or "unknown"
        node_label = eq.get("label")

        bbox_based_size = None
        bbox_w = None
        bbox_h = None
        raw_bbox = eq.get("bbox")
        if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
            try:
                bx1, by1, bx2, by2 = map(float, raw_bbox)
                bw = abs(bx2 - bx1)
                bh = abs(by2 - by1)
                bbox_w = bw
                bbox_h = bh
                if bw > 0.0 and bh > 0.0:
                    bbox_based_size = max(8.0, max(min(bw, bh) * 0.95, math.sqrt(bw * bh) * 0.9))
            except (TypeError, ValueError):
                bbox_based_size = None
                bbox_w = None
                bbox_h = None

        eq_symbol_size = eq.get("symbol_size")
        try:
            if eq_symbol_size is not None:
                draw_symbol_size = float(eq_symbol_size)
            elif bbox_based_size is not None:
                draw_symbol_size = float(bbox_based_size)
            else:
                draw_symbol_size = float(base_symbol_size)
        except (TypeError, ValueError):
            draw_symbol_size = base_symbol_size
        if draw_symbol_size <= 0.0:
            draw_symbol_size = base_symbol_size

        node = EquipmentNode(
            node_id=eq_id or f"GEO_{idx}",
            node_type=node_type,
            position=position,
            label=str(node_label) if node_label else None,
            symbol_width=(bbox_w * 0.92 if bbox_w and bbox_w > 0 else None),
            symbol_height=(bbox_h * 0.92 if bbox_h and bbox_h > 0 else None),
        )

        mapper.draw(msp, node, draw_symbol_size)

        template_has_text = False
        if isinstance(mapper, TemplateDrivenShapeMapper):
            tpl = mapper._get_template(node_type)
            if isinstance(tpl, Mapping):
                tpl_texts = tpl.get("texts", [])
                if (not isinstance(tpl_texts, list) or len(tpl_texts) == 0):
                    prim = tpl.get("primitives", {})
                    if isinstance(prim, Mapping):
                        tpl_texts = prim.get("texts", [])
                template_has_text = isinstance(tpl_texts, list) and len(tpl_texts) > 0

        label = eq.get("label")
        if label and not template_has_text:
            ext_label_height = max(0.55, min(2.0, float(draw_symbol_size) * 0.06))
            text = msp.add_text(
                str(label),
                dxfattribs={"height": ext_label_height, "layer": LAYER_LABELS},
            )
            text.set_placement(
                (
                    position[0] + float(draw_symbol_size) * 0.65,
                    position[1] + float(draw_symbol_size) * 0.2,
                )
            )

        if eq_id:
            seen_equipment.add(eq_id)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(output_path)
    return output_path


def _load_json_file(json_path: str | Path) -> Mapping[str, object]:
    json_path = Path(json_path)
    with json_path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, Mapping):
        raise SchemaValidationError("Input JSON root must be an object.")
    return data


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert structured P&ID JSON into DXF.")
    parser.add_argument("--input", required=True, help="Input JSON file path")
    parser.add_argument("--output", default="output.dxf", help="Output DXF file path")
    return parser


def main() -> int:
    args = build_cli_parser().parse_args()
    payload = _load_json_file(args.input)
    output_path = export_pid_json_to_dxf(payload=payload, output_path=args.output)
    print(f"DXF export successful: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
