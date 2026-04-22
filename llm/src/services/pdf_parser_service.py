import pdfplumber
from typing import List
from loguru import logger
from ..models.document import Block, BoundingBox

class PDFParserService:
    """Извлечение текста и координат из PDF с помощью pdfplumber."""

    @staticmethod
    def extract_blocks(pdf_path: str) -> List[Block]:
        blocks = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                words = page.extract_words()
                if not words:
                    logger.warning(f"Страница {page_num} не содержит слов")
                    continue

                # Сортируем слова по вертикали (top) и горизонтали (x0)
                words_sorted = sorted(words, key=lambda w: (w['top'], w['x0']))
                current_block = None

                for w in words_sorted:
                    # Проверяем наличие необходимых ключей
                    if not all(k in w for k in ('text', 'x0', 'x1', 'top', 'bottom')):
                        continue

                    if current_block is None:
                        current_block = {
                            'text': w['text'],
                            'x0': w['x0'],
                            'x1': w['x1'],
                            'top': w['top'],
                            'bottom': w['bottom'],
                        }
                    else:
                        # Если разница по top меньше порога (5 pt) — считаем одной строкой
                        if abs(w['top'] - current_block['top']) < 5:
                            current_block['text'] += ' ' + w['text']
                            current_block['x1'] = max(current_block['x1'], w['x1'])
                            current_block['bottom'] = max(current_block['bottom'], w['bottom'])
                        else:
                            # Завершаем текущий блок (строку)
                            blocks.append(
                                Block(
                                    type="paragraph",
                                    text=current_block['text'].strip(),
                                    page_number=page_num,
                                    bbox=BoundingBox(
                                        x0=current_block['x0'],
                                        y0=current_block['top'],
                                        x1=current_block['x1'],
                                        y1=current_block['bottom']
                                    )
                                )
                            )
                            # Начинаем новую строку
                            current_block = {
                                'text': w['text'],
                                'x0': w['x0'],
                                'x1': w['x1'],
                                'top': w['top'],
                                'bottom': w['bottom'],
                            }

                if current_block:
                    blocks.append(
                        Block(
                            type="paragraph",
                            text=current_block['text'].strip(),
                            page_number=page_num,
                            bbox=BoundingBox(
                                x0=current_block['x0'],
                                y0=current_block['top'],
                                x1=current_block['x1'],
                                y1=current_block['bottom']
                            )
                        )
                    )

        logger.info(f"Извлечено {len(blocks)} блоков из {pdf_path}")
        return blocks