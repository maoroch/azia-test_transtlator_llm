import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import simpleSplit
from reportlab.platypus import Table as RLTable, TableStyle
from reportlab.lib import colors
from typing import List
from loguru import logger
from ..models.document import Block, Table, BoundingBox

class PDFGeneratorService:
    @staticmethod
    def _draw_table(c, table: Table, bbox: BoundingBox):
        """Отрисовывает таблицу с авто-высотой строк."""
        data = table.data
        if not data:
            return
        font_name = PDFGeneratorService._get_font_name()
        font_size = 10
        c.setFont(font_name, font_size)
        bbox_width = bbox.x1 - bbox.x0
        num_cols = max(len(row) for row in data)
        cell_width = bbox_width / num_cols
        row_heights = []
        for row in data:
            max_height = font_size * 1.2
            for cell in row:
                if not cell:
                    continue
                lines = simpleSplit(cell, font_name, font_size, cell_width)
                cell_height = len(lines) * font_size * 1.2
                max_height = max(max_height, cell_height)
            row_heights.append(max_height)
        col_widths = [cell_width] * num_cols
        rl_table = RLTable(data, colWidths=col_widths, rowHeights=row_heights)
        style = TableStyle([
            ('GRID', (0,0), (-1,-1), 1, colors.black),
            ('FONTNAME', (0,0), (-1,-1), font_name),
            ('FONTSIZE', (0,0), (-1,-1), font_size),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ])
        rl_table.setStyle(style)
        w, h = rl_table.wrap(0, 0)
        rl_table.drawOn(c, bbox.x0, bbox.y1 - h)

    @staticmethod
    def _get_font_name():
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

        # Сортируем блоки по странице и по Y (сверху вниз)
        sorted_blocks = sorted(zip(blocks, translated_texts), key=lambda x: (x[0].page_number, x[0].bbox.y0))

        current_page = 1
        y_offset = 0

        for block, translation in sorted_blocks:
            if block.page_number != current_page:
                c.showPage()
                current_page = block.page_number
                y_offset = 0

            # Обработка таблиц
            if block.type == "table" and block.table_data:
                PDFGeneratorService._draw_table(c, block.table_data, block.bbox)
                continue

            # Обработка обычного текста
            block_width = block.bbox.x1 - block.bbox.x0
            if block_width <= 0:
                block_width = width - block.bbox.x0 - 50

            font_size = block.font_size if block.font_size and block.font_size > 0 else 12
            c.setFont(font_name, font_size)

            lines = simpleSplit(translation, font_name, font_size, block_width)
            line_height = font_size * 1.2
            text_height = len(lines) * line_height

            original_top = block.bbox.y0
            y_baseline = height - original_top - font_size
            y_baseline -= y_offset

            for i, line in enumerate(lines):
                y_line = y_baseline - i * line_height
                c.drawString(block.bbox.x0, y_line, line)

            original_height = block.bbox.y1 - block.bbox.y0
            new_height = text_height
            delta_height = new_height - original_height
            y_offset += max(0, delta_height)

        c.save()
        logger.info(f"PDF saved to {output_path}")