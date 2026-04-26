from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from src.models.document import Block

class UploadResponse(BaseModel):
    session_id: str
    page_count: int
    block_count: int

class BlockUpdate(BaseModel):
    blocks: List[Dict[str, Any]]   # список блоков в том же формате, что и в JSON

class GenerateResponse(BaseModel):
    download_url: str