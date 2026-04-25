import pdfplumber
from typing import List, Tuple, Any
from loguru import logger
from collections import Counter
from ..models.document import Block, BoundingBox, Table

class PDFParserService:
    @staticmethod
    def extract_blocks(pdf_path: str) -> List[Block]:
        all_blocks = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                # Извлечение таблиц с координатами ячеек
                table_blocks = PDFParserService._extract_tables_with_cells(page, page_num)
                all_blocks.extend(table_blocks)

                # Извлечение текстовых блоков (параграфы, заголовки и т.д.)
                words = page.extract_words()
                if words:
                    raw_blocks = PDFParserService._words_to_blocks(words, page_num)
                    classified_blocks = PDFParserService._classify_blocks(raw_blocks, page, page_num)
                    all_blocks.extend(classified_blocks)

                    # Очистка текста в каждом блоке
                    for blk in classified_blocks:
                        blk.text = PDFParserService._clean_text(blk.text)
                        # Затем объединение коротких блоков
                        classified_blocks = PDFParserService._merge_short_blocks(classified_blocks)

                else:
                    logger.warning(f"Страница {page_num} не содержит слов")
        logger.info(f"Извлечено {len(all_blocks)} блоков из {pdf_path}")
        tables = page.find_tables()
        print(f"Page {page_num}: found {len(tables)} tables")
        return all_blocks

    @staticmethod
    def _extract_tables_with_cells(page, page_num: int) -> List[Block]:
        table_blocks = []
        tables = page.find_tables()
        for table in tables:
            cells = []
            # Проверяем наличие ячеек
            if not hasattr(table, 'cells') or not table.cells:
                continue
            for row in table.cells:
                row_cells = []
                for cell in row:
                    # Убедимся, что cell — это кортеж из 4 чисел
                    if isinstance(cell, (tuple, list)) and len(cell) >= 4:
                        # Распаковываем координаты
                        x0, y0, x1, y1 = cell[0], cell[1], cell[2], cell[3]
                        cell_text = page.extract_text(clip=(x0, y0, x1, y1)) or ""
                        row_cells.append({
                            "text": cell_text.strip(),
                            "bbox": BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
                        })
                    else:
                        # Если ячейка не в ожидаемом формате, пропускаем
                        continue
                if row_cells:
                    cells.append(row_cells)
            if not cells:
                continue
            bbox = BoundingBox(x0=table.bbox[0], y0=table.bbox[1], x1=table.bbox[2], y1=table.bbox[3])
            table_block = Block(
                type="table",
                text="",
                page_number=page_num,
                bbox=bbox,
                table_data=Table(data=[], bbox=bbox, page_number=page_num, cells=cells)
            )
            table_blocks.append(table_block)
        return table_blocks
    
    @staticmethod
    def _words_to_blocks(words, page_num):
        blocks = []
        words_sorted = sorted(words, key=lambda w: (w['top'], w['x0']))
        current = None
        for w in words_sorted:
            if not all(k in w for k in ('text', 'x0', 'x1', 'top', 'bottom')):
                continue
            if current is None:
                current = {
                    'text': w['text'],
                    'x0': w['x0'],
                    'x1': w['x1'],
                    'top': w['top'],
                    'bottom': w['bottom'],
                }
            else:
                if abs(w['top'] - current['top']) < 5:
                    current['text'] += ' ' + w['text']
                    current['x1'] = max(current['x1'], w['x1'])
                    current['bottom'] = max(current['bottom'], w['bottom'])
                else:
                    blocks.append(Block(
                        type="paragraph",
                        text=current['text'].strip(),
                        page_number=page_num,
                        bbox=BoundingBox(
                            x0=current['x0'],
                            y0=current['top'],
                            x1=current['x1'],
                            y1=current['bottom']
                        )
                    ))
                    current = {
                        'text': w['text'],
                        'x0': w['x0'],
                        'x1': w['x1'],
                        'top': w['top'],
                        'bottom': w['bottom'],
                    }
        if current:
            blocks.append(Block(
                type="paragraph",
                text=current['text'].strip(),
                page_number=page_num,
                bbox=BoundingBox(
                    x0=current['x0'],
                    y0=current['top'],
                    x1=current['x1'],
                    y1=current['bottom']
                )
            ))
        return blocks

    @staticmethod
    def _classify_blocks(blocks: List[Block], page, page_num: int) -> List[Block]:
        if not page.chars:
            for b in blocks:
                b.type = "paragraph"
            return blocks

        all_sizes = [ch['size'] for ch in page.chars if 'size' in ch]
        avg_size = sum(all_sizes) / len(all_sizes) if all_sizes else 12.0

        for block in blocks:
            chars_in_block = []
            for ch in page.chars:
                if abs(ch['top'] - block.bbox.y0) > 5:
                    continue
                if not (ch['x0'] <= block.bbox.x1 + 5 and ch['x1'] >= block.bbox.x0 - 5):
                    continue
                chars_in_block.append(ch)

            if not chars_in_block:
                for ch in page.chars:
                    if (ch['x0'] >= block.bbox.x0 - 10 and ch['x1'] <= block.bbox.x1 + 10 and
                        ch['top'] >= block.bbox.y0 - 10 and ch['bottom'] <= block.bbox.y1 + 10):
                        chars_in_block.append(ch)

            if not chars_in_block:
                block.type = "paragraph"
                continue

            sizes = [ch['size'] for ch in chars_in_block if 'size' in ch]
            avg_block_size = sum(sizes) / len(sizes) if sizes else avg_size
            fontnames = [ch['fontname'] for ch in chars_in_block if 'fontname' in ch]
            common_font = Counter(fontnames).most_common(1)[0][0] if fontnames else ''

            text_len = len(block.text)

            if avg_block_size > avg_size + 2 and text_len < 80:
                block.type = "heading"
            elif text_len > 0 and (block.text[0] in ('•', '-', '*') or
                  (text_len > 2 and block.text[0].isdigit() and block.text[1] in ('.', ')'))):
                block.type = "list"
            else:
                block.type = "paragraph"

            block.font_size = avg_block_size
            block.font_name = common_font

        return blocks
    

    @staticmethod
    def _clean_text(text: str) -> str:
        """Удаляет мягкие переносы, управляющие символы, лишние дефисы."""
        import re
        # Удаляем символы мягкого переноса (shy)
        text = text.replace("\u00ad", "").replace("­", "")
        # Удаляем повторяющиеся дефисы и пробелы
        text = re.sub(r'\s*-\s*', '-', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @staticmethod
    def _merge_short_blocks(blocks: List[Block], max_length: int = 60) -> List[Block]:
        """Объединяет короткие последовательные блоки (не таблицы и не заголовки)."""
        if not blocks:
            return blocks
        merged = []
        i = 0
        while i < len(blocks):
            current = blocks[i]
            # Пропускаем таблицы и заголовки (они не объединяются)
            if current.type in ("table", "heading"):
                merged.append(current)
                i += 1
                continue
            # Ищем следующие короткие блоки на той же странице
            merged_text = current.text
            merged_bbox = current.bbox
            j = i + 1
            while j < len(blocks) and blocks[j].page_number == current.page_number and blocks[j].type not in ("table", "heading"):
                if len(blocks[j].text) < max_length:
                    merged_text += " " + blocks[j].text
                    # Расширяем bounding box
                    merged_bbox = BoundingBox(
                        x0=min(merged_bbox.x0, blocks[j].bbox.x0),
                        y0=min(merged_bbox.y0, blocks[j].bbox.y0),
                        x1=max(merged_bbox.x1, blocks[j].bbox.x1),
                        y1=max(merged_bbox.y1, blocks[j].bbox.y1)
                    )
                    j += 1
                else:
                    break
            if j > i + 1:
                # Создаём объединённый блок
                new_block = Block(
                    type=current.type,
                    text=merged_text,
                    page_number=current.page_number,
                    bbox=merged_bbox,
                    font_size=current.font_size,
                    font_name=current.font_name
                )
                merged.append(new_block)
            else:
                merged.append(current)
            i = j
        return merged