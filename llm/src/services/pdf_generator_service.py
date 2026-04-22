import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import simpleSplit
from typing import List
from loguru import logger
from ..models.document import Block

class PDFGeneratorService:
    @staticmethod
    def _get_font_name():
        """Возвращает имя зарегистрированного шрифта с кириллицей."""
        possible_fonts = [
            ("DejaVuSans", "DejaVuSans.ttf"),
            ("Arial", "/System/Library/Fonts/Supplemental/Arial.ttf"),
        ]
        for font_name, font_path in possible_fonts:
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont(font_name, font_path))
                    logger.info(f"Registered font: {font_name} from {font_path}")
                    return font_name
                except Exception as e:
                    logger.warning(f"Failed to register {font_path}: {e}")
        logger.warning("No Cyrillic font found, using Helvetica (Cyrillic may not render)")
        return "Helvetica"

    @staticmethod
    def generate_pdf(output_path: str, blocks: List[Block], translated_texts: List[str]):
        if len(blocks) != len(translated_texts):
            raise ValueError("Blocks and translations count mismatch")

        c = canvas.Canvas(output_path, pagesize=letter)
        width, height = letter
        font_name = PDFGeneratorService._get_font_name()

        # Сортировка блоков по странице и по Y (сверху вниз)
        # Предполагаем, что блоки уже приходят в порядке возрастания page_number и y0 (сверху вниз)
        # Убедимся: отсортируем
        sorted_blocks = sorted(zip(blocks, translated_texts), key=lambda x: (x[0].page_number, -x[0].bbox.y0))  # y0 сверху вниз: чем больше y0, тем выше. Но нужно по убыванию y0 (сначала верхние)
        # На самом деле y0 - это top, т.е. чем меньше число, тем выше? В pdfplumber top - это расстояние от верха страницы. Чем меньше top, тем выше.
        # Уточнение: в pdfplumber top - это y0 от верхнего края страницы. Значит, чем меньше top, тем выше на странице.
        # Поэтому сортируем по (page_number, block.bbox.y0) по возрастанию.
        sorted_blocks = sorted(zip(blocks, translated_texts), key=lambda x: (x[0].page_number, x[0].bbox.y0))

        current_page = 1
        # Смещение по Y для текущей страницы (накопленное из-за изменения высоты блоков)
        y_offset = 0

        for block, translation in sorted_blocks:
            # Если страница сменилась, сбрасываем offset и переключаем страницу
            if block.page_number != current_page:
                c.showPage()
                current_page = block.page_number
                y_offset = 0

            # Ширина блока (ограничение по горизонтали)
            block_width = block.bbox.x1 - block.bbox.x0
            if block_width <= 0:
                block_width = width - block.bbox.x0 - 50  # fallback

            # Размер шрифта
            font_size = block.font_size if block.font_size and block.font_size > 0 else 12
            c.setFont(font_name, font_size)

            # Разбиваем текст на строки, чтобы он не вылезал за правую границу
            # simpleSplit(text, font_name, font_size, max_width)
            from reportlab.lib.utils import simpleSplit
            lines = simpleSplit(translation, font_name, font_size, block_width)

            # Вычисляем высоту, которую займут строки (межстрочный интервал ~1.2 * font_size)
            line_height = font_size * 1.2
            text_height = len(lines) * line_height

            # Определяем Y-позицию для отрисовки
            # Оригинальный верхний край блока: block.bbox.y0 (top). В PDF координаты Y идут снизу вверх.
            # Переводим top в bottom: original_bottom = height - block.bbox.y1
            # Но мы хотим рисовать текст так, чтобы он начинался примерно с оригинального верхнего края.
            # Однако из-за возможного изменения высоты блока, последующие блоки сдвигаются.
            # Базовая позиция: верхний край оригинального блока (в координатах PDF)
            original_top = block.bbox.y0  # в pdfplumber top - расстояние от верха страницы
            # Преобразуем в координату Y для canvas (снизу вверх):
            y_baseline = height - original_top - font_size  # baseline первой строки

            # Применяем накопленное смещение (если предыдущие блоки увеличили высоту)
            y_baseline -= y_offset

            # Отрисовываем строки
            for i, line in enumerate(lines):
                y_line = y_baseline - i * line_height
                c.drawString(block.bbox.x0, y_line, line)

            # Обновляем смещение: разница между новой высотой блока и оригинальной
            original_height = block.bbox.y1 - block.bbox.y0
            new_height = text_height
            delta_height = new_height - original_height
            y_offset += max(0, delta_height)  # если текст стал выше, сдвигаем следующие блоки вниз
            # Если текст стал ниже (delta отрицательный), то не сдвигаем вверх, т.к. это может нарушить порядок. Лучше оставить как есть.

        c.save()
        logger.info(f"PDF saved to {output_path}")