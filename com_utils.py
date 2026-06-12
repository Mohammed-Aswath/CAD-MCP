import pythoncom
from typing import Iterable, List, Tuple
from win32com.client import VARIANT

Point3D = Tuple[float, float, float]


def flatten_points(points: Iterable[Point3D]) -> List[float]:
    flat: List[float] = []
    for point in points:
        if len(point) < 3:
            raise ValueError("Point must contain 3 numeric coordinates")
        flat.extend([float(point[0]), float(point[1]), float(point[2])])
    return flat


def to_variant_point(point: Point3D) -> VARIANT:
    if len(point) < 3:
        raise ValueError("Point must contain 3 numeric coordinates")
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, flatten_points([point]))


def to_variant_flat_points(coordinates: List[float]) -> VARIANT:
    """Create COM-safe VARIANT for lightweight polylines: [x1, y1, x2, y2, ...]"""
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, coordinates)


def to_variant_points(points: Iterable[Point3D]) -> VARIANT:
    """Create COM-safe VARIANT for general geometry operations: [x1, y1, z1, x2, y2, z2, ...]"""
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, flatten_points(points))
