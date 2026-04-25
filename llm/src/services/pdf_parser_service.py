import pdfplumber
from typing import List, Optional
from loguru import logger
from collections import Counter
from ..models.document import Block, BoundingBox, Table

class PDFParserService:
    @staticmethod
    def extract_blocks(pdf_path: str) -> List[Block]:
        all_blocks = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                # Извлечение таблиц
                table_blocks = PDFParserService._extract_tables_with_cells(page, page_num)
                all_blocks.extend(table_blocks)

                words = page.extract_words()
                if words:
                    raw_blocks = PDFParserService._words_to_blocks_v2(words, page_num)
                    classified_blocks = PDFParserService._classify_blocks(raw_blocks, page, page_num)
                    for blk in classified_blocks:
                        blk.text = PDFParserService._clean_text(blk.text)
                    classified_blocks = PDFParserService._merge_short_blocks(classified_blocks)
                    # Дополнительная нормализация: восстановление пробелов
                    for blk in classified_blocks:
                        blk.text = PDFParserService._normalize_spaces(blk.text)
                    all_blocks.extend(classified_blocks)
                else:
                    logger.warning(f"Страница {page_num} не содержит слов")
        logger.info(f"Извлечено {len(all_blocks)} блоков из {pdf_path}")
        return all_blocks

    @staticmethod
    def _extract_tables_with_cells(page, page_num: int) -> List[Block]:
        table_blocks = []
        tables = page.find_tables()
        for table in tables:
            cells = []
            if not hasattr(table, 'cells') or not table.cells:
                continue
            for row in table.cells:
                row_cells = []
                for cell in row:
                    if isinstance(cell, (tuple, list)) and len(cell) >= 4:
                        x0, y0, x1, y1 = cell[0], cell[1], cell[2], cell[3]
                        cell_text = page.extract_text(clip=(x0, y0, x1, y1)) or ""
                        row_cells.append({
                            "text": cell_text.strip(),
                            "bbox": BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
                        })
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
    def _words_to_blocks_v2(words, page_num):
        if not words:
            return []
        words_sorted = sorted(words, key=lambda w: (w['top'], w['x0']))

        lines = []
        current_line = []
        current_top = None
        for w in words_sorted:
            if current_top is None or abs(w['top'] - current_top) > 5:
                if current_line:
                    lines.append(current_line)
                current_line = [w]
                current_top = w['top']
            else:
                current_line.append(w)
        if current_line:
            lines.append(current_line)

        blocks = []
        for line in lines:
            text_parts = []
            prev_x1 = None
            for w in line:
                text = w['text']
                if prev_x1 is not None and (w['x0'] - prev_x1) > 1.5:
                    text_parts.append(' ')
                text_parts.append(text)
                prev_x1 = w['x1']
            line_text = ''.join(text_parts)
            # Удаляем мягкие переносы
            line_text = line_text.replace("\u00ad", "").replace("­", "")
            import re
            line_text = re.sub(r'\s+', ' ', line_text).strip()
            if line_text:
                x0 = min(w['x0'] for w in line)
                y0 = min(w['top'] for w in line)
                x1 = max(w['x1'] for w in line)
                y1 = max(w['bottom'] for w in line)
                blocks.append(Block(
                    type="paragraph",
                    text=line_text,
                    page_number=page_num,
                    bbox=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
                ))
        return blocks

    @staticmethod
    def _clean_text(text: str) -> str:
        import re
        text = text.replace("\u00ad", "").replace("­", "")
        text = re.sub(r'\s*-\s*', '-', text)
        text = re.sub(r'\s+', ' ', text)
        # Убираем маркеры разделителей из JSON (---)
        text = text.replace("---", "").strip()
        return text

    @staticmethod
    def _normalize_spaces(text: str) -> str:
        """Восстанавливает пробелы после знаков препинания и заглавных букв, если они слиты."""
        import re
        # После . , ; : ? ! пробел
        text = re.sub(r'([.,;:?!])([A-ZА-ЯЁ])', r'\1 \2', text)
        # Если идут две заглавные буквы подряд, вставляем пробел
        text = re.sub(r'([A-ZА-ЯЁ])([A-ZА-ЯЁ])', r'\1 \2', text)
        return text

    @staticmethod
    def _merge_short_blocks(blocks: List[Block], max_len: int = 60) -> List[Block]:
        if not blocks:
            return blocks
        merged = []
        i = 0
        while i < len(blocks):
            current = blocks[i]
            if current.type in ("table", "heading"):
                merged.append(current)
                i += 1
                continue
            merged_text = current.text
            merged_bbox = current.bbox
            j = i + 1
            while j < len(blocks) and blocks[j].page_number == current.page_number and blocks[j].type not in ("table", "heading"):
                if len(blocks[j].text) < max_len:
                    merged_text += " " + blocks[j].text
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

    # --- Оставшиеся методы без изменений ---
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