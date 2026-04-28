from typing import List, Dict, Any, Optional, Tuple
from loguru import logger
import uuid
from ..models.document import Block, BoundingBox

class BlockEditService:
    """
    Сервис для редактирования отдельных блоков и операций над ними:
    - Удаление блока
    - Дублирование блока
    - Перемещение блока на другую страницу
    - Изменение размера/позиции
    - Группировка блоков
    - Изменение типа блока
    """
    
    @staticmethod
    def delete_block(blocks: List[Dict[str, Any]], block_id: str) -> Tuple[List[Dict[str, Any]], bool]:
        """Удаляет блок по ID."""
        original_len = len(blocks)
        blocks = [b for b in blocks if b.get("id") != block_id]
        deleted = len(blocks) < original_len
        
        if deleted:
            logger.info(f"Block deleted: {block_id}")
        else:
            logger.warning(f"Block not found: {block_id}")
        
        return blocks, deleted
    
    @staticmethod
    def duplicate_block(blocks: List[Dict[str, Any]], block_id: str, 
                       offset_x: float = 20, offset_y: float = 20) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Дублирует блок с смещением."""
        source_block = next((b for b in blocks if b.get("id") == block_id), None)
        
        if not source_block:
            logger.warning(f"Source block not found: {block_id}")
            return blocks, None
        
        # Создаём копию
        new_block = {**source_block}
        new_block["id"] = str(uuid.uuid4())
        
        # Смещаем позицию
        new_block["bbox"] = {
            "x0": source_block["bbox"]["x0"] + offset_x,
            "y0": source_block["bbox"]["y0"] + offset_y,
            "x1": source_block["bbox"]["x1"] + offset_x,
            "y1": source_block["bbox"]["y1"] + offset_y,
        }
        
        # Для таблиц копируем cells
        if source_block.get("type") == "table" and source_block.get("table_data"):
            new_block["table_data"] = {**source_block["table_data"]}
            new_block["table_data"]["cells"] = [
                [cell.copy() for cell in row]
                for row in source_block["table_data"]["cells"]
            ]
        
        blocks.append(new_block)
        logger.info(f"Block duplicated: {block_id} -> {new_block['id']}")
        
        return blocks, new_block["id"]
    
    @staticmethod
    def move_to_page(blocks: List[Dict[str, Any]], block_id: str, new_page: int) -> Tuple[List[Dict[str, Any]], bool]:
        """Перемещает блок на другую страницу."""
        block = next((b for b in blocks if b.get("id") == block_id), None)
        
        if not block:
            logger.warning(f"Block not found: {block_id}")
            return blocks, False
        
        block["page_number"] = new_page
        logger.info(f"Block moved to page {new_page}: {block_id}")
        
        return blocks, True
    
    @staticmethod
    def update_position(blocks: List[Dict[str, Any]], block_id: str, 
                       x0: float, y0: float, x1: float, y1: float) -> Tuple[List[Dict[str, Any]], bool]:
        """Обновляет позицию и размер блока."""
        block = next((b for b in blocks if b.get("id") == block_id), None)
        
        if not block:
            logger.warning(f"Block not found: {block_id}")
            return blocks, False
        
        # Валидация координат
        if x0 >= x1 or y0 >= y1:
            logger.warning(f"Invalid coordinates for block {block_id}")
            return blocks, False
        
        block["bbox"] = {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
        logger.info(f"Block position updated: {block_id}")
        
        return blocks, True
    
    @staticmethod
    def update_text(blocks: List[Dict[str, Any]], block_id: str, 
                   new_text: str, is_translation: bool = True) -> Tuple[List[Dict[str, Any]], bool]:
        """Обновляет текст блока."""
        block = next((b for b in blocks if b.get("id") == block_id), None)
        
        if not block:
            logger.warning(f"Block not found: {block_id}")
            return blocks, False
        
        if block.get("type") == "table":
            logger.warning(f"Cannot update text for table block: {block_id}")
            return blocks, False
        
        if is_translation:
            block["text"] = new_text
        else:
            block["original_text"] = new_text
        
        logger.info(f"Block text updated: {block_id}")
        
        return blocks, True
    
    @staticmethod
    def change_block_type(blocks: List[Dict[str, Any]], block_id: str, 
                         new_type: str) -> Tuple[List[Dict[str, Any]], bool]:
        """Изменяет тип блока (paragraph, heading, list)."""
        valid_types = ["paragraph", "heading", "list", "table"]
        
        if new_type not in valid_types:
            logger.warning(f"Invalid block type: {new_type}")
            return blocks, False
        
        block = next((b for b in blocks if b.get("id") == block_id), None)
        
        if not block:
            logger.warning(f"Block not found: {block_id}")
            return blocks, False
        
        # Таблицы не меняем
        if block.get("type") == "table" or new_type == "table":
            logger.warning(f"Cannot change table block type: {block_id}")
            return blocks, False
        
        block["type"] = new_type
        logger.info(f"Block type changed: {block_id} -> {new_type}")
        
        return blocks, True
    
    @staticmethod
    def update_table_cell(blocks: List[Dict[str, Any]], block_id: str,
                         row: int, col: int, new_text: str) -> Tuple[List[Dict[str, Any]], bool]:
        """Обновляет текст в ячейке таблицы."""
        block = next((b for b in blocks if b.get("id") == block_id), None)
        
        if not block or block.get("type") != "table":
            logger.warning(f"Table block not found: {block_id}")
            return blocks, False
        
        table_data = block.get("table_data", {})
        cells = table_data.get("cells", [])
        
        if row < 0 or row >= len(cells) or col < 0 or col >= len(cells[row]):
            logger.warning(f"Invalid cell coordinates: row={row}, col={col}")
            return blocks, False
        
        cells[row][col]["text"] = new_text
        logger.info(f"Table cell updated: {block_id}[{row}][{col}]")
        
        return blocks, True
    
    @staticmethod
    def merge_blocks(blocks: List[Dict[str, Any]], block_ids: List[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Объединяет несколько блоков в один.
        Создаёт новый блок, охватывающий все выбранные.
        """
        source_blocks = [b for b in blocks if b.get("id") in block_ids]
        
        if len(source_blocks) < 2:
            logger.warning("Need at least 2 blocks to merge")
            return blocks, None
        
        # Проверяем, что все блоки на одной странице
        pages = set(b.get("page_number") for b in source_blocks)
        if len(pages) > 1:
            logger.warning("Cannot merge blocks from different pages")
            return blocks, None
        
        # Вычисляем новый bounding box
        min_x0 = min(b["bbox"]["x0"] for b in source_blocks)
        min_y0 = min(b["bbox"]["y0"] for b in source_blocks)
        max_x1 = max(b["bbox"]["x1"] for b in source_blocks)
        max_y1 = max(b["bbox"]["y1"] for b in source_blocks)
        
        # Собираем текст
        merged_text = " ".join(b.get("text", "") for b in source_blocks if b.get("type") != "table")
        
        # Создаём новый блок
        merged_block = {
            "id": str(uuid.uuid4()),
            "type": "paragraph",
            "text": merged_text,
            "original_text": " ".join(b.get("original_text", "") for b in source_blocks),
            "page_number": source_blocks[0]["page_number"],
            "bbox": {"x0": min_x0, "y0": min_y0, "x1": max_x1, "y1": max_y1},
            "font_size": source_blocks[0].get("font_size"),
            "font_name": source_blocks[0].get("font_name"),
        }
        
        # Удаляем исходные блоки
        blocks = [b for b in blocks if b.get("id") not in block_ids]
        blocks.append(merged_block)
        
        logger.info(f"Blocks merged: {block_ids} -> {merged_block['id']}")
        
        return blocks, merged_block["id"]
    
    @staticmethod
    def split_block(blocks: List[Dict[str, Any]], block_id: str, 
                   split_index: int) -> Tuple[List[Dict[str, Any]], Optional[Tuple[str, str]]]:
        """
        Разбивает блок по индексу символа.
        Возвращает IDs двух новых блоков.
        """
        block = next((b for b in blocks if b.get("id") == block_id), None)
        
        if not block or block.get("type") == "table":
            logger.warning(f"Cannot split block: {block_id}")
            return blocks, None
        
        text = block.get("text", "")
        if split_index <= 0 or split_index >= len(text):
            logger.warning(f"Invalid split index: {split_index}")
            return blocks, None
        
        # Разбиваем текст
        text_part1 = text[:split_index]
        text_part2 = text[split_index:]
        
        # Вычисляем примерное разделение bbox по ширине
        width = block["bbox"]["x1"] - block["bbox"]["x0"]
        split_width = width * (split_index / len(text))
        
        block1 = {
            "id": str(uuid.uuid4()),
            "type": block.get("type"),
            "text": text_part1,
            "original_text": block.get("original_text", "")[:split_index],
            "page_number": block["page_number"],
            "bbox": {
                "x0": block["bbox"]["x0"],
                "y0": block["bbox"]["y0"],
                "x1": block["bbox"]["x0"] + split_width,
                "y1": block["bbox"]["y1"],
            },
            "font_size": block.get("font_size"),
            "font_name": block.get("font_name"),
        }
        
        block2 = {
            "id": str(uuid.uuid4()),
            "type": block.get("type"),
            "text": text_part2,
            "original_text": block.get("original_text", "")[split_index:],
            "page_number": block["page_number"],
            "bbox": {
                "x0": block["bbox"]["x0"] + split_width,
                "y0": block["bbox"]["y0"],
                "x1": block["bbox"]["x1"],
                "y1": block["bbox"]["y1"],
            },
            "font_size": block.get("font_size"),
            "font_name": block.get("font_name"),
        }
        
        # Удаляем исходный блок
        blocks = [b for b in blocks if b.get("id") != block_id]
        blocks.extend([block1, block2])
        
        logger.info(f"Block split: {block_id} -> {block1['id']}, {block2['id']}")
        
        return blocks, (block1["id"], block2["id"])