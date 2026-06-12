from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

Point3D = Tuple[float, float, float]

class ConnectRequest(BaseModel):
    start_handle: str
    end_handle: str

class SymbolInsertRequest(BaseModel):
    block_name: str = Field(..., description="Symbol type/block name")
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    layer: str = "0"
    scale: float = 100.0

class DeleteRequest(BaseModel):
    handle: str

class MoveRequest(BaseModel):
    handle: str
    dx: float = 0.0
    dy: float = 0.0
    dz: float = 0.0

class RotateRequest(BaseModel):
    handle: str
    angle: float = 0.0
    base_x: float = 0.0
    base_y: float = 0.0
    base_z: float = 0.0

class EntityMetadata(BaseModel):
    handle: str
    entity_type: str
    block_name: Optional[str] = None
    insertion_point: Optional[Point3D] = None
    rotation: Optional[float] = None
    scale: Optional[float] = None
    layer: Optional[str] = None
    primitive_count: Optional[int] = None
    raw_type: Optional[str] = None
    vertices: Optional[List[Point3D]] = None
    radius: Optional[float] = None
    start_handle: Optional[str] = None
    end_handle: Optional[str] = None
    segment_handles: Optional[List[str]] = None
    route_points: Optional[List[Point3D]] = None
    connected_entities: Optional[List[str]] = None
    metadata: Optional[Dict[str, object]] = None

class DrawingDetails(BaseModel):
    document_name: str
    modelspace_count: int
    block_definitions: List[str]
    layers: List[str]
