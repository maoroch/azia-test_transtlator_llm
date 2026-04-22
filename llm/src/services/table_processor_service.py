from typing import List, Dict, Optional
from loguru import logger
from ..models.document import Table
from .translation_service import TranslationService

class TableProcessorService:
    def __init__(self, translation_service: TranslationService):
        self.translator = translation_service

    def translate_table(self, table: Table, src_lang: str, tgt_lang: str, glossary: Optional[Dict[str, str]] = None) -> Table:
        """Переводит все ячейки таблицы, сохраняя структуру."""
        new_data = []
        for row_idx, row in enumerate(table.data):
            new_row = []
            for cell_idx, cell in enumerate(row):
                if cell and cell.strip():
                    translated_cell = self._translate_cell(cell, src_lang, tgt_lang, glossary)
                    new_row.append(translated_cell)
                else:
                    new_row.append("")
                logger.debug(f"Translated cell [{row_idx},{cell_idx}]: '{cell}' -> '{translated_cell if cell else ''}'")
            new_data.append(new_row)
        return Table(data=new_data, bbox=table.bbox, page_number=table.page_number)

    def _translate_cell(self, text: str, src_lang: str, tgt_lang: str, glossary: Optional[Dict[str, str]]) -> str:
        """Переводит одну ячейку через Groq (с кэшированием)."""
        # Используем существующий метод _call_groq из TranslationService
        # Но нужно передать короткий промпт без контекста
        prompt = f"Translate the following term or short phrase from {src_lang} to {tgt_lang}. Return only the translation, no explanations.\n\n{text}"
        if glossary:
            gloss = "\n".join([f"'{k}' -> '{v}'" for k, v in glossary.items()])
            prompt = f"Use this glossary:\n{gloss}\n\n{prompt}"
        return self.translator._call_groq(prompt)