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
                # Таблицы с линиями и ячейками
                table_blocks = PDFParserService._extract_tables_with_lines(page, page_num)
                all_blocks.extend(table_blocks)

                # Текстовые блоки
                words = page.extract_words()
                if words:
                    raw_blocks = PDFParserService._words_to_blocks_v2(words, page_num)
                    classified_blocks = PDFParserService._classify_blocks(raw_blocks, page, page_num)
                    for blk in classified_blocks:
                        blk.text = PDFParserService._clean_text(blk.text)
                    # Не объединяем короткие блоки, чтобы не нарушать таблицы
                    # classified_blocks = PDFParserService._merge_short_blocks(classified_blocks)
                    all_blocks.extend(classified_blocks)
                else:
                    logger.warning(f"Страница {page_num} не содержит слов")
        logger.info(f"Извлечено {len(all_blocks)} блоков из {pdf_path}")
        return all_blocks

    @staticmethod
    def _extract_tables_with_lines(page, page_num: int) -> List[Block]:
        """Продвинутое извлечение таблиц с детекцией границ (линий/стенок)."""
        table_blocks = []
        
        # Пробуем разные стратегии
        strategies = [
            {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
            {"vertical_strategy": "text", "horizontal_strategy": "text"},
            {"vertical_strategy": "explicit", "horizontal_strategy": "explicit"},
        ]
        best_table = None
        best_score = 0
        
        for strat in strategies:
            try:
                tables = page.find_tables(**strat)
                for table in tables:
                    if table.cells and len(table.cells[0]) > 1 and len(table.cells) > 1:
                        score = len(table.cells) * len(table.cells[0])
                        if score > best_score:
                            best_score = score
                            best_table = table
            except:
                continue
        
        if best_table is None:
            return []
        
        # Извлечение ячеек
        cells = []
        for row in best_table.cells:
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
            return []
        
        # Извлечение линий (стенок) на странице
        borders = []
        for rect in page.rects:
            borders.append({
                "type": "rect",
                "x0": rect["x0"], "y0": rect["y0"],
                "x1": rect["x1"], "y1": rect["y1"],
            })
        for curve in page.curves:
            pts = curve["pts"]
            if len(pts) >= 2:
                borders.append({
                    "type": "line",
                    "x0": pts[0]["x"], "y0": pts[0]["y"],
                    "x1": pts[1]["x"], "y1": pts[1]["y"],
                })
        
        bbox = BoundingBox(x0=best_table.bbox[0], y0=best_table.bbox[1],
                           x1=best_table.bbox[2], y1=best_table.bbox[3])
        
        table_block = Block(
            type="table",
            text="",
            page_number=page_num,
            bbox=bbox,
            table_data=Table(
                data=[],
                bbox=bbox,
                page_number=page_num,
                cells=cells,
                cell_borders=borders
            )
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
            if current_top is None or abs(w['top'] - current_top) > 12:
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
                if prev_x1 is not None and (w['x0'] - prev_x1) > 4:
                    text_parts.append(' ')
                text_parts.append(text)
                prev_x1 = w['x1']
            line_text = ''.join(text_parts)
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
        return text

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