import redis
import json
import hashlib
from typing import Optional, Dict
from loguru import logger
from dotenv import load_dotenv
import os

load_dotenv()

class RedisCacheService:
    def __init__(self):
        self.host = os.getenv("REDIS_HOST", "localhost")
        self.port = int(os.getenv("REDIS_PORT", 6379))
        self.db = int(os.getenv("REDIS_DB", 0))
        self.client = redis.Redis(host=self.host, port=self.port, db=self.db, decode_responses=True)
        self._check_connection()

    def _check_connection(self):
        try:
            self.client.ping()
            logger.info(f"✅ Connected to Redis at {self.host}:{self.port}")
        except redis.ConnectionError:
            logger.warning("⚠️ Redis connection failed; caching disabled")
            self.client = None

    def _make_key(self, text: str, src_lang: str, tgt_lang: str, glossary: Optional[Dict[str, str]]) -> str:
        """Генерирует хеш-ключ для кэша."""
        glossary_str = json.dumps(glossary, sort_keys=True) if glossary else ""
        content = f"{text}|{src_lang}|{tgt_lang}|{glossary_str}"
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, text: str, src_lang: str, tgt_lang: str, glossary: Optional[Dict[str, str]]) -> Optional[str]:
        if not self.client:
            return None
        key = self._make_key(text, src_lang, tgt_lang, glossary)
        result = self.client.get(key)
        if result:
            logger.info(f"📦 CACHE HIT (key {key[:8]}...)")
            return result
        else:
            logger.info(f"🔁 CACHE MISS (key {key[:8]}...) — will call Groq API")
            return None

    def set(self, text: str, src_lang: str, tgt_lang: str, glossary: Optional[Dict[str, str]], translation: str, ttl_seconds: int = 86400):
        if not self.client:
            return
        key = self._make_key(text, src_lang, tgt_lang, glossary)
        self.client.setex(key, ttl_seconds, translation)
        logger.debug(f"💾 Cached translation for key {key[:8]}...")

    def clear(self):
        if self.client:
            self.client.flushdb()
            logger.info("🧹 Redis cache cleared")