import os
import re
import asyncio
from collections import defaultdict
from typing import List, Dict, Optional
from loguru import logger
from groq import AsyncGroq
from dotenv import load_dotenv
from .cache_service import RedisCacheService

load_dotenv()

class RateLimiter:
    def __init__(self, rate_per_minute: int):
        self.rate = rate_per_minute
        self.interval = 60.0 / rate_per_minute
        self.last = asyncio.get_event_loop().time()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = asyncio.get_event_loop().time()
            wait = self.last + self.interval - now
            if wait > 0:
                await asyncio.sleep(wait)
                self.last = asyncio.get_event_loop().time()
            else:
                self.last = now

class TranslationService:
    def __init__(self, api_key: Optional[str] = None, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not found")
        self.client = AsyncGroq(api_key=self.api_key)
        self.model = model
        self.cache = RedisCacheService()
        self.rate_limiter = RateLimiter(int(os.getenv("GROQ_RATE_LIMIT_PER_MINUTE", 30)))
        self.semaphore = asyncio.Semaphore(int(os.getenv("GROQ_MAX_CONCURRENT", 5)))

    async def _call_groq_with_retry(self, prompt: str, retries: int = 3) -> str:
        for attempt in range(retries):
            try:
                async with self.semaphore:
                    await self.rate_limiter.acquire()
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": "You are a professional technical translator. Translate accurately, preserve terminology, do not add comments."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.2,
                        max_tokens=2048
                    )
                    result = response.choices[0].message.content.strip()
                    result = re.sub(r'\s+', ' ', result)
                    result = result.replace("\u00ad", "").replace("­", "")
                    return result
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} failed: {e}")
                if attempt == retries - 1:
                    logger.error(f"Groq API error after {retries} attempts: {e}")
                    raise
                await asyncio.sleep(2 ** attempt)
        return "[TRANSLATION ERROR]"

    def translate_by_pages(self, blocks: List, src_lang: str, tgt_lang: str,
                           glossary: Optional[Dict[str, str]] = None,
                           max_blocks_per_req: int = 20) -> List[str]:
        return asyncio.run(self._translate_by_pages_async(blocks, src_lang, tgt_lang, glossary, max_blocks_per_req))

    def translate_blocks(self, blocks: List, src_lang: str, tgt_lang: str,
                         glossary: Optional[Dict[str, str]] = None,
                         batch_size: int = 20) -> List[str]:
        return self.translate_by_pages(blocks, src_lang, tgt_lang, glossary, max_blocks_per_req=batch_size)

    async def _translate_by_pages_async(self, blocks: List, src_lang: str, tgt_lang: str,
                                        glossary: Optional[Dict[str, str]],
                                        max_blocks_per_req: int) -> List[str]:
        page_map = defaultdict(list)
        for idx, blk in enumerate(blocks):
            page_map[blk.page_number].append((idx, blk))

        results = [""] * len(blocks)
        tasks = []
        task_info = []

        for page_num, page_blocks in page_map.items():
            for chunk_start in range(0, len(page_blocks), max_blocks_per_req):
                chunk = page_blocks[chunk_start:chunk_start+max_blocks_per_req]
                texts = [blk[1].text for blk in chunk]
                combined = "\n---\n".join(texts)

                cached = self.cache.get(combined, src_lang, tgt_lang, glossary)
                if cached:
                    parts = cached.split("\n---\n")
                    if len(parts) == len(chunk):
                        for (orig_idx, blk), trans in zip(chunk, parts):
                            results[orig_idx] = trans
                        continue

                prompt = self._build_prompt(combined, src_lang, tgt_lang, glossary)
                tasks.append(self._call_groq_with_retry(prompt))
                task_info.append((chunk, page_num, chunk_start))

        if tasks:
            responses = await asyncio.gather(*tasks)
            for resp, (chunk, page_num, start) in zip(responses, task_info):
                parts = TranslationService._split_response(resp, len(chunk))
                if len(parts) != len(chunk):
                    logger.warning(f"Page {page_num}: expected {len(chunk)} parts, got {len(parts)}.")
                    parts = (parts + [""] * len(chunk))[:len(chunk)]
                for (orig_idx, blk), trans in zip(chunk, parts):
                    trans = TranslationService._clean_translation(trans)
                    results[orig_idx] = trans
                    self.cache.set(blk.text, src_lang, tgt_lang, glossary, trans)
        return results

    @staticmethod
    def _split_response(response: str, expected: int) -> list:
        import re as _re
        normalized = _re.sub(r"(?m)^\s*[-–—]{2,}\s*$", "---", response)
        parts = [p.strip() for p in normalized.split("\n---\n")]
        if len(parts) != expected:
            parts2 = [p.strip() for p in _re.split(r"\n?---\n?", normalized)]
            if abs(len(parts2) - expected) < abs(len(parts) - expected):
                parts = parts2
        return [p for p in parts if p] or [response]

    @staticmethod
    def _clean_translation(text: str) -> str:
        import re as _re
        text = text.replace("\u00ad", "").replace("\xad", "")
        text = _re.sub(r"(?<![\w])-{3,}(?![\w])", "", text)
        text = _re.sub(r"[ \t]+", " ", text)
        text = _re.sub(r"\n+", " ", text)
        return text.strip()

    def _build_prompt(self, current_text: str, src_lang: str, tgt_lang: str,
                      glossary: Optional[Dict[str, str]]) -> str:
        lang_names = {
            "en": "English", "ru": "Russian", "kk": "Kazakh",
            "de": "German", "fr": "French", "es": "Spanish",
        }
        src_name = lang_names.get(src_lang, src_lang)
        tgt_name = lang_names.get(tgt_lang, tgt_lang)
        gloss = ""
        if glossary:
            gloss = "Use this terminology glossary:\n"
            gloss += "\n".join(f"  {k} -> {v}" for k, v in glossary.items())
            gloss += "\n\n"
        return (
            f"You are a professional technical translator. "
            f"Translate each text block from {src_name} to {tgt_name}.\n\n"
            f"{gloss}"
            "STRICT RULES:\n"
            "1. Each input block is delimited by the separator line containing only \"---\".\n"
            "2. Output EXACTLY the same number of blocks in the same order, each separated by exactly \"---\" on its own line.\n"
            "3. Do NOT add, remove, or merge blocks. Do NOT add commentary, notes, or explanations.\n"
            "4. Preserve all product names, model numbers, part numbers, brand names, and technical codes EXACTLY as written (e.g. testo 103, 1.4571, V4A, Reg. EU 1935/2004).\n"
            "5. Preserve punctuation structure. Do NOT add hyphens or dashes inside the translated text.\n"
            "6. Output ONLY the translated blocks separated by \"---\". Nothing else.\n\n"
            f"Input blocks:\n{current_text}"
        )

    async def translate_blocks_async(self, blocks: List, src_lang: str, tgt_lang: str,
                                 glossary: Optional[Dict[str, str]] = None,
                                 batch_size: int = 20) -> List[str]:

        """Асинхронная версия translate_blocks для использования в FastAPI."""
        return await self._translate_by_pages_async(blocks, src_lang, tgt_lang, glossary, max_blocks_per_req=batch_size)
