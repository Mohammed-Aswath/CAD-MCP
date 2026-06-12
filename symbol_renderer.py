import json
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from com_utils import to_variant_point, to_variant_flat_points

EQUIPMENT_LAYER = "EQUIPMENT"
PIPES_LAYER = "PIPES"

Point2D = Tuple[float, float]

logger = logging.getLogger(__name__)


class SymbolRenderer:
    def __init__(self, template_path: str = "symbol_templates.json") -> None:
        self.templates: Dict[str, object] = {}
        self._current_symbol_name: Optional[str] = None
        path = Path(template_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        try:
            with path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.templates = loaded
            self._log("RENDER", f"Loaded {len(self.templates)} templates from {path}")
        except Exception as exc:
            self._log("RENDER", f"Failed to load templates from {path}: {exc}")
            self.templates = {}

    def _log(self, category: str, message: str) -> None:
        logger.info("[%s] %s", category, message)

    def render_symbol(
        self,
        msp,
        symbol_name: str,
        x: float,
        y: float,
        scale: float = 100.0,
        rotation: float = 0.0,
        layer: str = EQUIPMENT_LAYER,
    ) -> List:
        self._current_symbol_name = symbol_name
        template = self._get_template(symbol_name)
        if template is None:
            self._log("RENDER", f"Template not found for '{symbol_name}', using fallback square.")
            return [self._draw_fallback(msp, x, y, scale, rotation, layer, {})]

        primitives = template.get("primitives", {}) if isinstance(template, dict) else {}
        lines = self._safe_list(primitives.get("lines"))
        circles = self._safe_list(primitives.get("circles"))
        contours = self._safe_list(primitives.get("contours"))
        primitive_texts = self._safe_list(primitives.get("texts"))
        top_texts = self._safe_list(template.get("texts"))
        texts = primitive_texts + top_texts

        fill = template.get("fill", {}) if isinstance(template, dict) else {}
        contour_fills = self._safe_list(fill.get("contours"))
        circle_fills = self._safe_list(fill.get("circles"))
        style = self._get_style(template)

        self._log(
            "RENDER",
            f"Rendering symbol '{symbol_name}' at ({x},{y}) scale={scale} rotation={rotation} layer={layer}"
        )
        self._log(
            "RENDER",
            f"Symbol primitives: contours={len(contours)} lines={len(lines)} circles={len(circles)} texts={len(texts)}"
        )

        entities: List[Any] = []

        for index, contour in enumerate(contours):
            fill_mode = self._resolve_fill_mode(contour_fills, index)
            contour_entities = self._draw_contour(
                msp,
                contour,
                x,
                y,
                scale,
                rotation,
                layer,
                style,
                fill_mode,
            )
            entities.extend(contour_entities)

        for index, circle in enumerate(circles):
            fill_mode = self._resolve_fill_mode(circle_fills, index)
            circle_entities = self._draw_circle(
                msp,
                circle,
                x,
                y,
                scale,
                rotation,
                layer,
                style,
                fill_mode,
            )
            if circle_entities:
                entities.extend(circle_entities)

        for line in lines:
            line_entity = self._draw_line(msp, line, x, y, scale, rotation, layer, style)
            if line_entity is not None:
                entities.append(line_entity)

        for text in texts:
            text_entity = self._draw_text(msp, text, x, y, scale, rotation, layer, style)
            if text_entity is not None:
                entities.append(text_entity)

        if not entities:
            self._log("RENDER", f"No geometry created for '{symbol_name}', using fallback square.")
            entities.append(self._draw_fallback(msp, x, y, scale, rotation, layer, style))

        return entities

    def _safe_list(self, value: Any) -> List:
        return list(value) if isinstance(value, (list, tuple)) else []

    def _resolve_fill_mode(self, fill_list: List, index: int) -> str:
        if index < len(fill_list):
            mode = str(fill_list[index] or "").strip().lower()
            return mode if mode in ("filled", "none") else "none"
        return "none"

    def _get_style(self, template: Dict[str, Any]) -> Dict[str, Any]:
        style = template.get("style", {}) if isinstance(template, dict) else {}
        if not isinstance(style, dict):
            style = {}
        try:
            color = int(style.get("color", 7))  # Default to white for all symbol geometry
        except Exception:
            color = 7
        hatch_pattern = str(style.get("hatch_pattern", "SOLID") or "SOLID")
        try:
            text_height_multiplier = float(style.get("text_height_multiplier", 1.0) or 1.0)
        except Exception:
            text_height_multiplier = 1.0
        try:
            lineweight = int(style.get("lineweight", -1))
            if lineweight < 0:
                lineweight = None
        except Exception:
            lineweight = None
        try:
            transparency = int(style.get("transparency", 0))
            if transparency < 0:
                transparency = 0
            if transparency > 90:
                transparency = 90
        except Exception:
            transparency = 0
        return {
            "color": color,
            "lineweight": lineweight,
            "linetype": style.get("linetype"),
            "text_height_multiplier": text_height_multiplier,
            "hatch_pattern": hatch_pattern,
            "transparency": transparency,
        }

    def _get_template(self, symbol_name: str) -> Optional[Dict[str, object]]:
        if not self.templates:
            return None
        key = str(symbol_name or "").strip().lower()
        if not key:
            return None
        template = self.templates.get(key)
        if isinstance(template, dict):
            return template
        for k, v in self.templates.items():
            if str(k).strip().lower() == key and isinstance(v, dict):
                return v
        return None

    def transform_point(
        self,
        x: float,
        y: float,
        cx: float,
        cy: float,
        scale: float,
        rotation: float,
    ) -> Point2D:
        """
        Transform a point from symbol-space to world-space.
        
        Detects coordinate format:
        - [0..1] normalized format (standard)
        - [0..150] pixel-like format
        - Already local coordinates
        """
        x = float(x)
        y = float(y)
        
        # Detect and normalize coordinate format
        # Normalized [0..1] format
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
            local_x = (x - 0.5) * scale
            local_y = (0.5 - y) * scale
        # Pixel-like [0..150] format (legacy)
        elif 0.0 <= x <= 150.0 and 0.0 <= y <= 150.0:
            local_x = ((x / 128.0) - 0.5) * scale
            local_y = (0.5 - (y / 128.0)) * scale
        # Already local coordinates
        else:
            local_x = x
            local_y = y
        
        # Apply rotation
        theta = math.radians(rotation)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        rx = local_x * cos_t - local_y * sin_t
        ry = local_x * sin_t + local_y * cos_t
        
        # Apply world translation
        world_x = cx + rx
        world_y = cy + ry
        self._log("TRANSFORM", f"Point ({x:.3f},{y:.3f}) -> local ({local_x:.3f},{local_y:.3f}) -> world ({world_x:.3f},{world_y:.3f}) rot={rotation}°")
        return (world_x, world_y)

    def compute_symbol_bounds(
        self,
        symbol_name: str,
        x: float = 0.0,
        y: float = 0.0,
        scale: float = 100.0,
        rotation: float = 0.0,
    ) -> Optional[Tuple[float, float, float, float]]:
        template = self._get_template(symbol_name)
        if template is None:
            return None

        primitives = template.get("primitives", {}) if isinstance(template, dict) else {}
        points: List[Point2D] = []

        for contour in self._safe_list(primitives.get("contours")):
            for pt in self._safe_list(contour):
                if isinstance(pt, (list, tuple)) and len(pt) == 2:
                    points.append(self.transform_point(pt[0], pt[1], x, y, scale, rotation))

        for circle in self._safe_list(primitives.get("circles")):
            if isinstance(circle, (list, tuple)) and len(circle) == 3:
                world_x, world_y = self.transform_point(circle[0], circle[1], x, y, scale, rotation)
                radius = float(circle[2]) * scale
                points.extend([
                    (world_x - radius, world_y - radius),
                    (world_x + radius, world_y + radius),
                ])

        for line in self._safe_list(primitives.get("lines")):
            if isinstance(line, (list, tuple)) and len(line) == 4:
                points.append(self.transform_point(line[0], line[1], x, y, scale, rotation))
                points.append(self.transform_point(line[2], line[3], x, y, scale, rotation))

        for text in self._safe_list(self._safe_list(primitives.get("texts")) + self._safe_list(template.get("texts"))):
            if isinstance(text, (list, tuple)) and len(text) >= 2:
                points.append(self.transform_point(text[0], text[1], x, y, scale, rotation))

        if not points:
            return None

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return (min(xs), min(ys), max(xs), max(ys))

    def _add_entity_attributes(self, entity, layer: str, style: Optional[Dict[str, Any]] = None) -> None:
        if style is None:
            style = {}
        try:
            entity.Layer = layer
        except Exception:
            pass
        # Apply color from style (default: 7 = white)
        color = style.get("color", 7)
        if color is not None:
            try:
                entity.Color = int(color)
            except Exception:
                pass
        # Apply lineweight for better visibility
        lineweight = style.get("lineweight")
        if lineweight is not None:
            try:
                entity.LineWeight = int(lineweight)
            except Exception:
                # LineWeight might be specified differently; try alternative
                try:
                    # Some entities use different property names
                    if hasattr(entity, 'LineWeight'):
                        entity.LineWeight = int(lineweight)
                except Exception:
                    pass
        # Apply linetype (solid, dashed, etc.)
        linetype = style.get("linetype")
        if linetype:
            try:
                entity.Linetype = str(linetype)
            except Exception:
                pass
        # Apply transparency if specified (0-90)
        transparency = style.get("transparency")
        if transparency is not None:
            try:
                entity.Transparency = int(transparency)
            except Exception:
                pass

    def _draw_text(
        self,
        msp,
        text_data,
        cx: float,
        cy: float,
        scale: float,
        rotation: float,
        layer: str,
        style: Dict[str, Any],
    ):
        if not isinstance(text_data, (list, tuple)) or len(text_data) < 4:
            self._log("TEXT", "Skipping invalid text primitive")
            return None
        try:
            x = float(text_data[0])
            y = float(text_data[1])
            text = str(text_data[2])
            text_scale = float(text_data[3])
        except (TypeError, ValueError) as exc:
            self._log("TEXT", f"Invalid text primitive values: {exc}")
            return None

        world_x, world_y = self.transform_point(x, y, cx, cy, scale, rotation)

        # Get the actual symbol size for proportional text scaling
        symbol_bounds = self.compute_symbol_bounds(
            self._current_symbol_name or "unknown",
            cx, cy, scale, rotation
        )

        if symbol_bounds:
            symbol_width = symbol_bounds[2] - symbol_bounds[0]
            symbol_height = symbol_bounds[3] - symbol_bounds[1]
            symbol_size = min(symbol_width, symbol_height)
            # Make text size proportional to symbol size (about 15-20% of symbol size)
            base_height = symbol_size * 0.18
        else:
            # Fallback to scale-based sizing if bounds can't be computed
            base_height = scale * 0.5

        height = max(1.0, text_scale * base_height)
        height = min(height, scale * 0.4)

        # Adjust for long text to keep it inside symbol
        text_length = max(1, len(text))
        approx_width = text_length * height * 0.55
        if symbol_bounds:
            max_text_width = symbol_width * 0.8
        else:
            max_text_width = scale * 0.75

        if approx_width > max_text_width:
            height = max(1.0, max_text_width / (text_length * 0.55))

        height = max(1.0, height * style.get("text_height_multiplier", 1.0))

        try:
            insertion_point = to_variant_point((world_x, world_y, 0.0))
            text_entity = msp.AddText(text, insertion_point, height)
            try:
                # AutoCAD text alignment center
                text_entity.Alignment = 1
            except Exception:
                pass
            try:
                text_entity.AlignmentPoint = to_variant_point((world_x, world_y, 0.0))
            except Exception:
                pass
            try:
                text_entity.Rotation = math.radians(rotation)
            except Exception:
                pass
            self._add_entity_attributes(text_entity, layer, style)
            self._log("TEXT", f"Rendered text '{text}' at ({world_x:.3f},{world_y:.3f}) height={height:.3f} alignment=Center (proportional to symbol size)")
            return text_entity
        except Exception as exc:
            self._log("TEXT", f"Failed to draw text '{text}': {exc}")
            return None

    def _draw_contour(
        self,
        msp,
        contour,
        cx: float,
        cy: float,
        scale: float,
        rotation: float,
        layer: str,
        style: Dict[str, Any],
        fill_mode: str = "none",
    ) -> List:
        entities: List[Any] = []

        if not isinstance(contour, list) or len(contour) < 3:
            self._log("RENDER", "Skipping invalid contour primitive")
            return entities

        flat_points: List[float] = []
        for pt in contour:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                self._log("RENDER", f"Skipping invalid contour point: {pt}")
                continue
            try:
                world_x, world_y = self.transform_point(pt[0], pt[1], cx, cy, scale, rotation)
            except (TypeError, ValueError):
                self._log("RENDER", f"Failed to transform contour point: {pt}")
                continue
            flat_points.extend([world_x, world_y])

        if len(flat_points) < 6:
            self._log("RENDER", "Contour has insufficient points")
            return entities

        try:
            poly = msp.AddLightWeightPolyline(to_variant_flat_points(flat_points))
            try:
                poly.Closed = True
            except Exception:
                pass
            self._add_entity_attributes(poly, layer, style)
            entities.append(poly)
            self._log("CONTOUR", f"Created contour with {len(flat_points)//2} vertices")
            if fill_mode == "filled":
                hatch = self._draw_hatch(msp, poly, layer, style)
                if hatch is not None:
                    entities.append(hatch)
        except Exception as exc:
            self._log("CONTOUR", f"Failed to draw contour: {exc}")

        return entities

    def _draw_circle(
        self,
        msp,
        circle,
        cx: float,
        cy: float,
        scale: float,
        rotation: float,
        layer: str,
        style: Dict[str, Any],
        fill_mode: str = "none",
    ) -> List:
        entities: List[Any] = []
        if not isinstance(circle, (list, tuple)) or len(circle) != 3:
            self._log("RENDER", "Skipping invalid circle primitive")
            return entities
        try:
            x = float(circle[0])
            y = float(circle[1])
            r = float(circle[2])
        except (TypeError, ValueError):
            self._log("RENDER", "Skipping circle with invalid values")
            return entities

        world_x, world_y = self.transform_point(x, y, cx, cy, scale, rotation)
        radius = r * scale

        try:
            circ = msp.AddCircle(to_variant_point((world_x, world_y, 0.0)), radius)
            self._add_entity_attributes(circ, layer, style)
            entities.append(circ)
            self._log("CIRCLE", f"Created circle at ({world_x:.3f},{world_y:.3f}) r={radius}")
            if fill_mode == "filled":
                hatch = self._draw_hatch(msp, circ, layer, style)
                if hatch is not None:
                    entities.append(hatch)
        except Exception as exc:
            self._log("CIRCLE", f"Failed to draw circle: {exc}")

        return entities

    def _draw_line(
        self,
        msp,
        line,
        cx: float,
        cy: float,
        scale: float,
        rotation: float,
        layer: str,
        style: Dict[str, Any],
    ):
        if not isinstance(line, (list, tuple)) or len(line) != 4:
            self._log("RENDER", "Skipping invalid line primitive")
            return None
        try:
            x1, y1, x2, y2 = float(line[0]), float(line[1]), float(line[2]), float(line[3])
        except (TypeError, ValueError):
            self._log("RENDER", "Skipping line with invalid values")
            return None

        world_p1 = self.transform_point(x1, y1, cx, cy, scale, rotation)
        world_p2 = self.transform_point(x2, y2, cx, cy, scale, rotation)
        try:
            line_entity = msp.AddLine(
                to_variant_point((world_p1[0], world_p1[1], 0.0)),
                to_variant_point((world_p2[0], world_p2[1], 0.0)),
            )
            self._add_entity_attributes(line_entity, layer, style)
            self._log("LINE", f"Created line from ({world_p1[0]:.3f},{world_p1[1]:.3f}) to ({world_p2[0]:.3f},{world_p2[1]:.3f})")
            return line_entity
        except Exception as exc:
            self._log("LINE", f"Failed to draw line: {exc}")
            return None

    def _draw_hatch(self, msp, boundary_entity, layer: str, style: Dict[str, Any]):
        try:
            pattern = str(style.get("hatch_pattern", "SOLID") or "SOLID")
            hatch = msp.AddHatch(0, pattern, True)
            try:
                hatch.AppendOuterLoop(boundary_entity)
            except Exception:
                try:
                    hatch.AppendLoop(1, boundary_entity)
                except Exception:
                    pass
            try:
                hatch.Evaluate()
            except Exception:
                pass
            # Apply style attributes including color for filled hatches
            self._add_entity_attributes(hatch, layer, style)
            # Force white fill for all filled shapes
            try:
                hatch.Color = 7
            except Exception:
                pass
            try:
                # Set transparency if available
                transparency = style.get("transparency", 0)
                if transparency and transparency > 0:
                    hatch.Transparency = int(transparency)
            except Exception:
                pass
            self._log("HATCH", f"Created hatch for boundary {getattr(boundary_entity, 'Handle', '<unknown>')} pattern={pattern} color=7 (white fill)")
            return hatch
        except Exception as exc:
            self._log("HATCH", f"Failed to create hatch: {exc}")
            return None

    def _draw_fallback(self, msp, cx, cy, scale, rotation, layer, style: Optional[Dict[str, Any]] = None):
        if style is None:
            style = {}
        half = scale * 0.5
        points = [
            (-half, -half),
            (half, -half),
            (half, half),
            (-half, half),
        ]
        flat_points: List[float] = []
        for px, py in points:
            rx = px * math.cos(math.radians(rotation)) - py * math.sin(math.radians(rotation))
            ry = px * math.sin(math.radians(rotation)) + py * math.cos(math.radians(rotation))
            flat_points.extend([cx + rx, cy + ry])
        try:
            poly = msp.AddLightWeightPolyline(to_variant_flat_points(flat_points))
            try:
                poly.Closed = True
            except Exception:
                pass
            self._add_entity_attributes(poly, layer, style)
            self._log("RENDER", "Fallback square created successfully")
            return poly
        except Exception as exc:
            self._log("RENDER", f"Fallback draw failed: {exc}")
            raise
