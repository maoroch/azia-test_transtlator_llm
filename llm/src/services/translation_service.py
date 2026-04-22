import os
from typing import List, Dict, Optional
from loguru import logger
from groq import Groq
from dotenv import load_dotenv
from .cache_service import RedisCacheService

load_dotenv()

class TranslationService:
    def __init__(self, api_key: Optional[str] = None, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not found in environment")
        self.client = Groq(api_key=self.api_key)
        self.model = model
        self.cache = RedisCacheService()  # используем Redis

    def translate_blocks(self, blocks: List, src_lang: str, tgt_lang: str, glossary: Optional[Dict[str, str]] = None) -> List[str]:
        translated = []
        previous_block_text = ""

        for i, block in enumerate(blocks):
            # Проверяем кэш Redis
            cached = self.cache.get(block.text, src_lang, tgt_lang, glossary)
            if cached:
                translated_text = cached
                logger.debug(f"Cache hit for block {i}")
            else:
                prompt = self._build_prompt(block.text, previous_block_text, src_lang, tgt_lang, glossary)
                translated_text = self._call_groq(prompt)
                # Сохраняем в Redis
                self.cache.set(block.text, src_lang, tgt_lang, glossary, translated_text)
                logger.info(f"Translated block {i+1}/{len(blocks)}")

            translated.append(translated_text)
            previous_block_text = block.text

        return translated


    def _build_prompt(self, current_text: str, prev_text: str, src_lang: str, tgt_lang: str, glossary: Optional[Dict[str, str]]) -> str:
        """Формирует промпт для LLM с контекстом и глоссарием."""
        context = ""
        if prev_text:
            context = f"Previous text for context:\n{prev_text}\n\n"
        glossary_text = ""
        if glossary:
            gloss = "\n".join([f"'{k}' -> '{v}'" for k, v in glossary.items()])
            glossary_text = f"Use this glossary for technical terms:\n{gloss}\n\n"
        prompt = f"""{context}{glossary_text}Translate the following text from {src_lang} to {tgt_lang}.
Keep the original formatting (line breaks, punctuation, numbers, code). Return only the translation, no explanations.

Text to translate:
{current_text}"""
        return prompt

    def _call_groq(self, prompt: str) -> str:
        """Отправляет запрос к Groq API и возвращает ответ."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a professional technical translator. Translate accurately, preserve terminology, do not add comments."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=2048
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            return f"[TRANSLATION ERROR: {e}]"