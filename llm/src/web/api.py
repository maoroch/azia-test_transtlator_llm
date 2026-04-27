import os
import uuid
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import redis
import json
from loguru import logger

from src.services.pdf_parser_service import PDFParserService
from src.services.pdf_generator_service import PDFGeneratorService
from src.services.translation_service import TranslationService
from src.models.document import Block
from src.web.models import UploadResponse, BlockUpdate, GenerateResponse

app = FastAPI(title="PDF Translator Editor")

# Разрешаем запросы с фронтенда (localhost:8080)
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

# ----------------------- Эндпоинты -----------------------

@app.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...)):
    session_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{session_id}.pdf")
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        blocks = parser.extract_blocks(file_path)
    except Exception as e:
        logger.error(f"Parsing failed: {e}")
        raise HTTPException(status_code=400, detail="Failed to parse PDF")
    blocks_data = [block.model_dump() for block in blocks]
    data = {
        "file_path": file_path,
        "page_count": max([b["page_number"] for b in blocks_data], default=0),
        "blocks": blocks_data
    }
    redis_key = f"session:{session_id}"
    if redis_client:
        redis_client.setex(redis_key, 86400, json.dumps(data))
    else:
        app.state.sessions = getattr(app.state, 'sessions', {})
        app.state.sessions[session_id] = data
    return UploadResponse(
        session_id=session_id,
        page_count=data["page_count"],
        block_count=len(blocks_data)
    )

@app.get("/blocks/{session_id}")
async def get_blocks(session_id: str):
    data = _get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse(content={"blocks": data["blocks"]})

@app.post("/translate/{session_id}")
async def translate_session(session_id: str, src_lang: str = "en", tgt_lang: str = "ru"):
    data = _get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    blocks = [Block.model_validate(b) for b in data["blocks"]]
    translator = TranslationService()
    # Используем асинхронный метод
    translated_texts = await translator.translate_blocks_async(blocks, src_lang, tgt_lang, glossary=None, batch_size=1)
    for i, block in enumerate(blocks):
        block.text = translated_texts[i]
    data["blocks"] = [b.model_dump() for b in blocks]
    _save_session(session_id, data)
    return {"status": "translated"}
@app.post("/redetect_table/{session_id}/{page_num}")
async def redetect_table(session_id: str, page_num: int):
    data = _get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    # Здесь можно было бы повторно открыть PDF и перепарсить таблицы,
    # но для краткости просто возвращаем статус.
    # В реальной реализации нужно заменить все блоки таблиц на странице.
    return {"status": "not implemented in this version, but you can refresh or reload"}

@app.post("/blocks/{session_id}")
async def update_blocks(session_id: str, update: BlockUpdate):
    data = _get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    data["blocks"] = update.blocks
    _save_session(session_id, data)
    return JSONResponse(content={"status": "ok"})

@app.post("/generate/{session_id}", response_model=GenerateResponse)
async def generate_pdf(session_id: str):
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
    file_path = os.path.join(UPLOAD_DIR, f"{session_id}_out.pdf")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found, please generate first")
    return FileResponse(file_path, filename=f"edited_{session_id}.pdf", media_type="application/pdf")

# ----------------------- Вспомогательные функции -----------------------

def _get_session(session_id: str):
    redis_key = f"session:{session_id}"
    if redis_client:
        raw = redis_client.get(redis_key)
        return json.loads(raw) if raw else None
    else:
        return getattr(app.state, 'sessions', {}).get(session_id)

def _save_session(session_id: str, data: dict):
    redis_key = f"session:{session_id}"
    if redis_client:
        redis_client.setex(redis_key, 86400, json.dumps(data))
    else:
        if not hasattr(app.state, 'sessions'):
            app.state.sessions = {}
        app.state.sessions[session_id] = data