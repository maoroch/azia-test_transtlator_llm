import os
import re
import fitz  # PyMuPDF
from typing import List, Optional, Tuple
from loguru import logger
from ..models.document import Block, Table

# ------------------------------------------------------------------ #
# Поиск шрифта с поддержкой кириллицы                                #
# ------------------------------------------------------------------ #

FONT_CANDIDATES = [
    # Linux (apt install fonts-liberation / fonts-freefont-ttf / fonts-noto)
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    # Windows (wine / docker)
    "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

def _find_font() -> Optional[str]:
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            logger.info(f"Using font: {p}")
            return p
    logger.warning("No Cyrillic font found — Latin fallback (helv)")
    return None

_FONT_PATH: Optional[str] = _find_font()


class PDFGeneratorService:

    # ------------------------------------------------------------------ #
    # Главная функция                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def generate_pdf(
        input_pdf_path: str,
        output_pdf_path: str,
        blocks: List[Block],
        translated_texts: List[str],
    ):
        if len(blocks) != len(translated_texts):
            raise ValueError("blocks / translations count mismatch")

        doc = fitz.open(input_pdf_path)

        # Пары (block, translation), отсортированные по странице и Y
        pairs = sorted(
            zip(blocks, translated_texts),
            key=lambda x: (x[0].page_number, x[0].bbox.y0),
        )

        # ---- Этап 1: редэкшн оригинального текста ----
        redact_pages: set = set()
        for block, _ in pairs:
            if block.type == "table":
                continue
            pg = doc[block.page_number - 1]
            rect = fitz.Rect(
                block.bbox.x0 - 1, block.bbox.y0 - 1,
                block.bbox.x1 + 1, block.bbox.y1 + 1,
            )
            pg.add_redact_annot(rect, fill=None)
            redact_pages.add(block.page_number - 1)

        for pn in redact_pages:
            doc[pn].apply_redactions()

        # ---- Этап 2: вставка переведённого текста ----
        for block, translation in pairs:
            if block.type == "table":
                PDFGeneratorService._draw_table(doc[block.page_number - 1], block.table_data)
            else:
                PDFGeneratorService._draw_text_block(
                    doc[block.page_number - 1], block, translation
                )

        doc.save(output_pdf_path, deflate=True)
        doc.close()
        logger.info(f"PDF saved → {output_pdf_path}")

    # ------------------------------------------------------------------ #
    # Вставка текстового блока                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _draw_text_block(page, block: Block, text: str):
        bbox = block.bbox
        font_size = block.font_size or 11.0
        font_size = max(6.0, min(font_size, 72.0))

        rect = fitz.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
        block_h = rect.height
        block_w = rect.width

        # Подбираем размер шрифта так, чтобы текст влез в блок
        chosen_size, lines = PDFGeneratorService._fit_text(
            text, font_size, block_w, block_h
        )

        # Вставляем строки
        line_h = chosen_size * 1.35
        y = bbox.y0 + chosen_size  # fitz ставит baseline, не top

        for line in lines:
            if not line.strip():
                y += line_h * 0.5
                continue
            PDFGeneratorService._insert_line(page, bbox.x0, y, line, chosen_size)
            y += line_h

    @staticmethod
    def _fit_text(
        text: str, base_size: float, width: float, height: float
    ) -> Tuple[float, List[str]]:
        """Уменьшает font_size пока текст не влезет в (width × height)."""
        size = base_size
        for _ in range(8):  # максимум 8 итераций уменьшения
            lines = PDFGeneratorService._wrap_text(text, size, width)
            line_h = size * 1.35
            total_h = line_h * len(lines)
            if total_h <= height + size or size <= 6.5:
                return size, lines
            size = max(6.0, size - 1.0)
        return size, PDFGeneratorService._wrap_text(text, size, width)

    @staticmethod
    def _wrap_text(text: str, font_size: float, max_width: float) -> List[str]:
        """Разбивает текст на строки, учитывая приблизительную ширину символов."""
        # Коэффициент ширины символа (monospace-приближение для CJK-safe)
        char_w = font_size * 0.52
        max_chars = max(1, int(max_width / char_w))

        words = text.split()
        lines: List[str] = []
        current: List[str] = []
        current_len = 0

        for word in words:
            # +1 за пробел перед словом
            add = len(word) + (1 if current else 0)
            if current and current_len + add > max_chars:
                lines.append(" ".join(current))
                current = [word]
                current_len = len(word)
            else:
                current.append(word)
                current_len += add

        if current:
            lines.append(" ".join(current))
        return lines if lines else [text]

    @staticmethod
    def _insert_line(page, x: float, y: float, text: str, font_size: float):
        if _FONT_PATH:
            page.insert_text(
                (x, y), text,
                fontsize=font_size,
                fontname="mainfont",
                fontfile=_FONT_PATH,
            )
        else:
            page.insert_text((x, y), text, fontsize=font_size, fontname="helv")

    # ------------------------------------------------------------------ #
    # Таблицы                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _draw_table(page, table: Table):
        if not table or not table.cells:
            return

        for row in table.cells:
            for cell in row:
                text = cell.get("text", "") if isinstance(cell, dict) else ""
                if not text.strip():
                    continue
                bbox = cell["bbox"] if isinstance(cell, dict) else cell.bbox
                x0, y0 = bbox.x0, bbox.y0
                x1, y1 = bbox.x1, bbox.y1
                w = x1 - x0
                h = y1 - y0
                padding = 2.0

                chosen_size, lines = PDFGeneratorService._fit_text(
                    text, font_size=9.0, width=w - padding * 2, height=h - padding * 2
                )
                line_h = chosen_size * 1.35
                y = y0 + padding + chosen_size

                for line in lines:
                    if y > y1 - padding:
                        break
                    PDFGeneratorService._insert_line(
                        page, x0 + padding, y, line, chosen_size
                    )
                    y += line_h
