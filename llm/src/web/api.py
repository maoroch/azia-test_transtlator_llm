import os
import uuid
import shutil
import json
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import redis
from loguru import logger

from src.services.pdf_parser_service import PDFParserService
from src.services.pdf_generator_service import PDFGeneratorService
from src.services.translation_service import TranslationService
from src.models.document import Block
from src.web.models import UploadResponse, BlockUpdate, GenerateResponse
from src.services.edit_history_service import EditHistoryService
from src.services.block_edit_service import BlockEditService

app = FastAPI(title="PDF Translator Editor Enhanced")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
try:
    redis_client.ping()
    logger.info("Connected to Redis")
except redis.ConnectionError:
    logger.warning("Redis not available, using in-memory fallback")
    redis_client = None

UPLOAD_DIR = "data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

parser = PDFParserService()
generator = PDFGeneratorService()

# ====================== Модели ======================

from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class BlockActionRequest(BaseModel):
    """Запрос для операции над блоком."""
    action: str  # delete, duplicate, move, update_position, update_text, change_type, merge, split
    block_id: Optional[str] = None
    block_ids: Optional[List[str]] = None
    data: Optional[Dict[str, Any]] = None

class UndoRedoRequest(BaseModel):
    """Запрос для undo/redo."""
    operation: str  # undo или redo

# ====================== Сессии с историей ======================

# В реальной системе это должно быть в Redis
sessions = {}  # session_id -> {"file_path", "page_count", "blocks", "history": EditHistoryService}

def _get_session(session_id: str):
    """Получить данные сессии."""
    redis_key = f"session:{session_id}"
    if redis_client:
        raw = redis_client.get(redis_key)
        return json.loads(raw) if raw else None
    else:
        return sessions.get(session_id)

def _save_session(session_id: str, data: dict):
    """Сохранить данные сессии."""
    redis_key = f"session:{session_id}"
    if redis_client:
        redis_client.setex(redis_key, 86400, json.dumps(data))
    else:
        sessions[session_id] = data

def _get_history(session_id: str) -> Optional[EditHistoryService]:
    """Получить историю редактирования для сессии."""
    history_key = f"history:{session_id}"
    if not hasattr(app.state, 'histories'):
        app.state.histories = {}
    
    if history_key not in app.state.histories:
        app.state.histories[history_key] = EditHistoryService()
    
    return app.state.histories[history_key]

# ====================== Основные эндпоинты ======================

@app.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...)):
    """Загрузить PDF и разбить на блоки."""
    session_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{session_id}.pdf")
    
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    try:
        blocks = parser.extract_blocks(file_path)
    except Exception as e:
        logger.error(f"Parsing failed: {e}")
        raise HTTPException(status_code=400, detail="Failed to parse PDF")
    
    # Добавляем ID каждому блоку
    blocks_data = []
    for block in blocks:
        block_dict = block.model_dump()
        block_dict["id"] = str(uuid.uuid4())
        blocks_data.append(block_dict)
    
    data = {
        "file_path": file_path,
        "page_count": max([b["page_number"] for b in blocks_data], default=0),
        "blocks": blocks_data
    }
    
    _save_session(session_id, data)
    
    # Инициализируем историю
    history = _get_history(session_id)
    history.add_state(blocks_data, "PDF uploaded")
    
    return UploadResponse(
        session_id=session_id,
        page_count=data["page_count"],
        block_count=len(blocks_data)
    )

@app.get("/blocks/{session_id}")
async def get_blocks(session_id: str):
    """Получить все блоки для сессии."""
    data = _get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse(content={"blocks": data["blocks"]})

@app.post("/translate/{session_id}")
async def translate_session(session_id: str, src_lang: str = "en", tgt_lang: str = "ru"):
    """Перевести документ."""
    data = _get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    
    blocks = [Block.model_validate(b) for b in data["blocks"]]
    translator = TranslationService()
    
    translated_texts = await translator.translate_blocks_async(
        blocks, src_lang, tgt_lang, glossary=None, batch_size=1
    )
    
    # Обновляем блоки с переводами
    for i, block_dict in enumerate(data["blocks"]):
        block_dict["text"] = translated_texts[i]
    
    _save_session(session_id, data)
    
    # Сохраняем в историю
    history = _get_history(session_id)
    history.add_state(data["blocks"], "Document translated", 
                     {"src_lang": src_lang, "tgt_lang": tgt_lang})
    
    return {"status": "translated"}

@app.post("/blocks/{session_id}")
async def update_blocks(session_id: str, update: BlockUpdate):
    """Обновить блоки."""
    data = _get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    
    data["blocks"] = update.blocks
    _save_session(session_id, data)
    
    history = _get_history(session_id)
    history.add_state(data["blocks"], "Blocks updated")
    
    return JSONResponse(content={"status": "ok"})

# ====================== Эндпоинты редактирования блоков ======================

@app.post("/blocks/{session_id}/action")
async def block_action(session_id: str, request: BlockActionRequest):
    data = _get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    
    blocks = data["blocks"]
    action_type = request.action
    action_data = request.data or {}
    success = False
    result = {}
    
    try:
        if action_type == "delete":
            blocks, success = BlockEditService.delete_block(blocks, request.block_id)
            result = {"deleted": success}
        
        elif action_type == "duplicate":
            blocks, new_id = BlockEditService.duplicate_block(
                blocks,
                request.block_id,
                offset_x=action_data.get("offset_x", 20),
                offset_y=action_data.get("offset_y", 20)
            )
            success = new_id is not None
            result = {"new_block_id": new_id}
        
        elif action_type == "move":
            blocks, success = BlockEditService.move_to_page(
                blocks,
                request.block_id,
                action_data.get("new_page")
            )
        
        elif action_type == "update_position":
            blocks, success = BlockEditService.update_position(
                blocks,
                request.block_id,
                action_data.get("x0"),
                action_data.get("y0"),
                action_data.get("x1"),
                action_data.get("y1")
            )
        
        elif action_type == "update_text":
            blocks, success = BlockEditService.update_text(
                blocks,
                request.block_id,
                action_data.get("text"),
                is_translation=action_data.get("is_translation", True)
            )
        
        elif action_type == "change_type":
            blocks, success = BlockEditService.change_block_type(
                blocks,
                request.block_id,
                action_data.get("new_type")
            )
        
        elif action_type == "update_table_cell":
            blocks, success = BlockEditService.update_table_cell(
                blocks,
                request.block_id,
                action_data.get("row"),
                action_data.get("col"),
                action_data.get("text")
            )
        
        elif action_type == "merge":
            blocks, merged_id = BlockEditService.merge_blocks(
                blocks,
                request.block_ids or []   # используем block_ids из запроса
            )
            success = merged_id is not None
            result = {"merged_block_id": merged_id}
        
        elif action_type == "split":
            blocks, split_ids = BlockEditService.split_block(
                blocks,
                request.block_id,
                action_data.get("split_index")
            )
            success = split_ids is not None
            result = {"block_ids": split_ids}
        
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action_type}")
        
        if not success:
            raise HTTPException(status_code=400, detail=f"Action failed: {action_type}")
        
        data["blocks"] = blocks
        _save_session(session_id, data)
        
        history = _get_history(session_id)
        history.add_state(blocks, f"Block action: {action_type}", action_data)
        
        result["status"] = "ok"
        return JSONResponse(content=result)
    
    except Exception as e:
        logger.error(f"Block action failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
# ====================== Эндпоинты Undo/Redo ======================

@app.post("/undo/{session_id}")
async def undo(session_id: str):
    """Отменить последнее действие."""
    data = _get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    
    history = _get_history(session_id)
    blocks = history.undo()
    
    if blocks is None:
        raise HTTPException(status_code=400, detail="Cannot undo")
    
    data["blocks"] = blocks
    _save_session(session_id, data)
    
    return JSONResponse(content={
        "status": "ok",
        "blocks": blocks,
        "history_info": history.get_history_info()
    })

@app.post("/redo/{session_id}")
async def redo(session_id: str):
    """Вернуть отменённое действие."""
    data = _get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    
    history = _get_history(session_id)
    blocks = history.redo()
    
    if blocks is None:
        raise HTTPException(status_code=400, detail="Cannot redo")
    
    data["blocks"] = blocks
    _save_session(session_id, data)
    
    return JSONResponse(content={
        "status": "ok",
        "blocks": blocks,
        "history_info": history.get_history_info()
    })

@app.get("/history/{session_id}")
async def get_history(session_id: str):
    """Получить информацию об истории редактирования."""
    history = _get_history(session_id)
    return JSONResponse(content=history.get_history_info())

# ====================== Генерация PDF и загрузка ======================

@app.post("/generate/{session_id}", response_model=GenerateResponse)
async def generate_pdf(session_id: str):
    """Сгенерировать итоговый PDF."""
    data = _get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    
    blocks = [Block.model_validate(b) for b in data["blocks"]]
    original_path = data["file_path"]
    output_path = os.path.join(UPLOAD_DIR, f"{session_id}_out.pdf")
    translated_texts = [b.text for b in blocks]
    
    generator.generate_pdf(original_path, output_path, blocks, translated_texts)
    
    return GenerateResponse(download_url=f"/download/{session_id}")

@app.get("/download/{session_id}")
async def download_pdf(session_id: str):
    """Скачать результирующий PDF."""
    file_path = os.path.join(UPLOAD_DIR, f"{session_id}_out.pdf")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found, please generate first")
    return FileResponse(file_path, filename=f"edited_{session_id}.pdf", media_type="application/pdf")

# ====================== Экспорт/импорт ======================

@app.get("/export/{session_id}")
async def export_blocks_json(session_id: str):
    """Экспортировать блоки в JSON."""
    data = _get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return JSONResponse(content=data["blocks"])

@app.post("/import/{session_id}")
async def import_blocks_json(session_id: str, blocks_data: List[Dict]):
    """Импортировать блоки из JSON."""
    data = _get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Валидируем структуру
    for block in blocks_data:
        if not all(k in block for k in ["id", "type", "page_number", "bbox"]):
            raise HTTPException(status_code=400, detail="Invalid block structure")
    
    data["blocks"] = blocks_data
    _save_session(session_id, data)
    
    history = _get_history(session_id)
    history.add_state(data["blocks"], "Blocks imported from JSON")
    
    return JSONResponse(content={"status": "ok"})