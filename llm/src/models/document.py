from pydantic import BaseModel
from typing import List, Optional, Literal, Dict, Any

class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float

class Table(BaseModel):
    data: List[List[str]] = []
    bbox: BoundingBox
    page_number: int
    cells: List[List[Dict[str, Any]]] = []
    cell_borders: Optional[List[Dict[str, Any]]] = None

class Block(BaseModel):
    type: Literal["paragraph", "heading", "list", "table", "other"]
    text: str = ""
    original_text: str = ""
    page_number: int
    bbox: BoundingBox
    font_size: Optional[float] = None
    font_name: Optional[str] = None
    table_data: Optional[Table] = None
    raw_data: Optional[dict] = None

class Document(BaseModel):
    file_path: str
    pages: int
    blocks: List[Block]