from pydantic import BaseModel
from typing import List, Optional, Literal

class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float

class Block(BaseModel):
    type: Literal["paragraph", "heading", "list", "table", "other"]
    text: str
    page_number: int
    bbox: BoundingBox
    font_size: Optional[float] = None
    font_name: Optional[str] = None
    raw_data: Optional[dict] = None

class Document(BaseModel):
    file_path: str
    pages: int
    blocks: List[Block]