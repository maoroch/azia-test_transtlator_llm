import json
import re
from typing import List, Dict, Optional
from loguru import logger
from ..models.document import Table
from .translation_service import TranslationService

class TableProcessorService:
    def __init__(self, translation_service: TranslationService):
        self.translator = translation_service

    def translate_table(self, table: Table, src_lang: str, tgt_lang: str, glossary: Optional[Dict[str, str]] = None) -> Table:
        """Переводит всю таблицу целиком, используя структуру cells."""
        if not table.cells:
            logger.warning("Table has no cells, translation skipped")
            return table

        # Собираем матрицу текста ячеек
        matrix = [[cell["text"] for cell in row] for row in table.cells]
        matrix_json = json.dumps(matrix, ensure_ascii=False)
        gloss_str = self._glossary_to_str(glossary)

        prompt = f"""Translate the following table from {src_lang} to {tgt_lang}.
Preserve the exact structure (number of rows and columns). Keep numbers, special characters unchanged.
Return the result as a JSON array of arrays of strings. Do not add any extra text.

Original table (JSON):
{matrix_json}

Glossary (use where possible):
{gloss_str}

Translated table (JSON):"""

        response = self.translator._call_groq(prompt)
        # Извлечь JSON из ответа
        translated_matrix = self._extract_json(response, matrix)
        # Обновить ячейки
        new_cells = []
        for i, row in enumerate(table.cells):
            new_row = []
            for j, cell in enumerate(row):
                new_cell = cell.copy()
                new_cell["text"] = translated_matrix[i][j] if i < len(translated_matrix) and j < len(translated_matrix[i]) else cell["text"]
                new_row.append(new_cell)
            new_cells.append(new_row)
        return Table(data=[], bbox=table.bbox, page_number=table.page_number, cells=new_cells)

    def _glossary_to_str(self, glossary):
        if not glossary:
            return "–"
        return "\n".join([f"'{k}' → '{v}'" for k, v in glossary.items()])

    def _extract_json(self, text, fallback_matrix):
        """Извлекает JSON из ответа LLM, при ошибке возвращает fallback."""
        text = text.strip()
        # Удаляем возможные маркеры кода
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        try:
            return json.loads(text)
        except:
            # Пробуем найти массив в тексте
            match = re.search(r'\[\[.*\]\]', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except:
                    pass
            logger.error(f"Failed to parse LLM response, using original table. Response snippet: {text[:200]}")
            return fallback_matrix