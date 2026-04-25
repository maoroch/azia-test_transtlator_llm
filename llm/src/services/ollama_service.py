import httpx
import asyncio
from collections import defaultdict
from typing import List, Optional, Dict
from loguru import logger
from .cache_service import RedisCacheService

class OllamaTranslationService:
    def __init__(self, model: str = "llama3:8b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
        self.cache = RedisCacheService()
        self.client = httpx.AsyncClient(timeout=120.0)

    async def _call_ollama(self, prompt: str) -> str:
        """Асинхронный вызов Ollama."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 2048
                    }
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["response"].strip()
        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            return f"[TRANSLATION ERROR: {e}]"

    def translate_blocks(self, blocks: List, src_lang: str, tgt_lang: str,
                         glossary: Optional[Dict[str, str]] = None,
                         batch_size: int = 20) -> List[str]:
        """Синхронная обёртка для постраничного перевода."""
        return asyncio.run(self._translate_by_pages(blocks, src_lang, tgt_lang, glossary, batch_size))

    async def _translate_by_pages(self, blocks: List, src_lang: str, tgt_lang: str,
                                  glossary: Optional[Dict[str, str]],
                                  max_blocks_per_req: int) -> List[str]:
        """Группирует блоки по страницам и переводит каждую страницу за один запрос."""
        # Группируем индексы блоков по страницам
        pages = defaultdict(list)
        for idx, blk in enumerate(blocks):
            pages[blk.page_number].append((idx, blk))

        results = [""] * len(blocks)
        tasks = []
        task_infos = []

        for page_num, page_blocks in pages.items():
            # Разбиваем страницу на чанки по max_blocks_per_req
            for chunk_start in range(0, len(page_blocks), max_blocks_per_req):
                chunk = page_blocks[chunk_start:chunk_start+max_blocks_per_req]
                texts = [blk[1].text for blk in chunk]
                combined = "\n---\n".join(texts)

                # Проверяем кэш
                cached = self.cache.get(combined, src_lang, tgt_lang, glossary)
                if cached:
                    parts = cached.split("\n---\n")
                    if len(parts) == len(chunk):
                        for (idx, _), trans in zip(chunk, parts):
                            results[idx] = trans
                        continue

                prompt = self._build_prompt(combined, "", src_lang, tgt_lang, glossary)
                tasks.append(self._call_ollama(prompt))   # <-- исправлено: вызов _call_ollama
                task_infos.append((chunk, page_num, chunk_start))

        if tasks:
            responses = await asyncio.gather(*tasks)
            for resp, (chunk, page_num, start) in zip(responses, task_infos):
                parts = resp.split("\n---\n")
                if len(parts) != len(chunk):
                    logger.warning(f"Page {page_num}: expected {len(chunk)} parts, got {len(parts)}. Using fallback.")
                    parts = [resp] * len(chunk)
                for (idx, _), trans in zip(chunk, parts):
                    results[idx] = trans
                    # Можно сохранить в кэш (опционально)
                    # self.cache.set(combined, src_lang, tgt_lang, glossary, resp) – но combined может повторяться для разных страниц
        return results

    def _build_prompt(self, current_text: str, prev_text: str, src_lang: str,
                      tgt_lang: str, glossary: Optional[Dict[str, str]]) -> str:
        context = f"Previous text:\n{prev_text}\n\n" if prev_text else ""
        gloss = ""
        if glossary:
            gloss = "\n".join([f"'{k}' -> '{v}'" for k, v in glossary.items()]) + "\n\n"
        return f"""{context}{gloss}Translate the following text(s) from {src_lang} to {tgt_lang}.
Each text block is separated by '---'. Preserve the separators in output. Return only the translation(s).

Text(s) to translate:
{current_text}"""