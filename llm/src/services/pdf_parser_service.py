import pdfplumber
from typing import List
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
                tables = page.extract_tables()
                if tables:
                    for table_data in tables:
                        # Приблизительный bbox: используем всю страницу или можно уточнить
                        # Для простоты используем всю страницу
                        bbox = BoundingBox(x0=0, y0=0, x1=page.width, y1=page.height)
                        table_block = Block(
                            type="table",
                            text="",
                            page_number=page_num,
                            bbox=bbox,
                            table_data=Table(data=table_data, bbox=bbox, page_number=page_num)
                        )
                        all_blocks.append(table_block)

                # Извлечение текстовых блоков
                words = page.extract_words()
                if not words:
                    logger.warning(f"Страница {page_num} не содержит слов")
                    continue

                raw_blocks = PDFParserService._words_to_blocks(words, page_num)
                classified_blocks = PDFParserService._classify_blocks(raw_blocks, page, page_num)
                all_blocks.extend(classified_blocks)

        logger.info(f"Извлечено {len(all_blocks)} блоков из {pdf_path}")
        return all_blocks

    @staticmethod
    def _words_to_blocks(words, page_num):
        """Группирует слова в строки (блоки) без классификации."""
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