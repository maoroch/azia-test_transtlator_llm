import os
import fitz  # PyMuPDF
from typing import List
from loguru import logger
from ..models.document import Block, Table

class PDFGeneratorService:
    @staticmethod
    def _split_text(text: str, font_size: float, max_width: float) -> List[str]:
        """Разбивает текст на строки, не превышающие max_width (приблизительно)."""
        # Простейший алгоритм: разбиваем по словам
        words = text.split()
        lines = []
        current_line = []
        for word in words:
            # Очень грубая оценка ширины: длина слова в символах * (font_size * 0.6)
            # В реальности лучше использовать библиотеку для измерения, но для простоты так.
            test_line = ' '.join(current_line + [word])
            approx_width = len(test_line) * font_size * 0.6
            if approx_width <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        if current_line:
            lines.append(' '.join(current_line))
        return lines if lines else [text]

    @staticmethod
    def _draw_table(page, table: Table, font_path: str):
        """Отрисовывает таблицу по координатам ячеек."""
        for row in table.cells:
            for cell in row:
                text = cell["text"]
                if not text.strip():
                    continue
                bbox = cell["bbox"]
                # Вычисляем размер шрифта (можно извлечь из оригинала, но пока фиксированный)
                font_size = 10
                # Разбиваем текст на строки по ширине ячейки
                block_width = bbox.x1 - bbox.x0
                lines = PDFGeneratorService._split_text(text, font_size, block_width)
                line_height = font_size * 1.2
                y = bbox.y0 + 2  # небольшой отступ сверху
                for line in lines:
                    if font_path:
                        page.insert_text((bbox.x0 + 2, y), line, fontsize=font_size, fontname="Arial", fontfile=font_path)
                    else:
                        page.insert_text((bbox.x0 + 2, y), line, fontsize=font_size, fontname="helv")
                    y += line_height

    @staticmethod
    def generate_pdf(input_pdf_path: str, output_pdf_path: str, blocks: List[Block], translated_texts: List[str]):
        """
        Накладывает переведённый текст поверх оригинального PDF, сохраняя изображения,
        фон и графику. Оригинальный текст удаляется через редэкшн.
        """
        if len(blocks) != len(translated_texts):
            raise ValueError("Blocks and translations count mismatch")

        doc = fitz.open(input_pdf_path)
        # Сортируем блоки по странице и Y-координате (сверху вниз)
        sorted_blocks = sorted(zip(blocks, translated_texts), key=lambda x: (x[0].page_number, x[0].bbox.y0))

        # --- Этап 1: Создаём редэкшн-аннотации для всех текстовых блоков ---
        current_page = -1
        page = None
        redact_rects = []  # (page_num, rect)

        for block, _ in sorted_blocks:
            page_num = block.page_number - 1
            if page_num != current_page:
                current_page = page_num
                page = doc[page_num]

            # Для таблиц пока не удаляем текст (можно доработать)
            if block.type == "table":
                continue

            # Расширяем bounding box немного (для надёжности)
            rect = fitz.Rect(block.bbox.x0 - 2, block.bbox.y0 - 2,
                             block.bbox.x1 + 2, block.bbox.y1 + 2)
            # Добавляем аннотацию редэкшн (удалит текст, фон остаётся)
            page.add_redact_annot(rect, fill=None)   # fill=None – прозрачный фон
            redact_rects.append((page_num, rect))

        # Применяем редэкшн на каждой странице (физически удаляем текст)
        for page_num in set(r[0] for r in redact_rects):
            doc[page_num].apply_redactions()

        # --- Этап 2: Вставляем переведённый текст поверх ---
        # Для кириллицы нужен шрифт с поддержкой. PyMuPDF умеет использовать системные шрифты.
        # Загрузим Arial (есть на macOS). Для Linux/Windows путь может отличаться.
        font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
        if not os.path.exists(font_path):
            # fallback – Helvetica без кириллицы
            font_path = None
            logger.warning("Arial.ttf not found, Cyrillic may not render")

        for block, translation in sorted_blocks:
            if block.type == "table":
                # Пропускаем таблицы (пока не реализовано)
                continue

            page_num = block.page_number - 1
            page = doc[page_num]
            bbox = block.bbox
            font_size = block.font_size if block.font_size else 12

            # Разбиваем перевод на строки
            block_width = bbox.x1 - bbox.x0
            lines = PDFGeneratorService._split_text(translation, font_size, block_width)
            line_height = font_size * 1.2

            # Вставляем строки, начиная с верхнего края блока
            y = bbox.y0  # в координатах PDF (сверху вниз)
            for line in lines:
                # Вставка текста
                if font_path:
                    page.insert_text((bbox.x0, y), line, fontsize=font_size, fontname="Arial", fontfile=font_path)
                else:
                    page.insert_text((bbox.x0, y), line, fontsize=font_size, fontname="helv")
                y += line_height

        doc.save(output_pdf_path)
        doc.close()
        logger.info(f"PDF saved to {output_pdf_path} (graphics preserved, text replaced)")