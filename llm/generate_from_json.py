#!/usr/bin/env python
import json
import argparse
import fitz  # PyMuPDF
from pathlib import Path
from loguru import logger

def split_lines(text, font_size, max_width):
    """Разбивает текст на строки, не превышающие max_width (приблизительная ширина)."""
    words = text.split()
    lines = []
    cur = []
    for w in words:
        test = ' '.join(cur + [w])
        approx_width = len(test) * font_size * 0.6
        if approx_width <= max_width:
            cur.append(w)
        else:
            if cur:
                lines.append(' '.join(cur))
            cur = [w]
    if cur:
        lines.append(' '.join(cur))
    return lines if lines else [text]

def fit_text_to_cell(text, max_width, max_height, font_path, max_font=12, min_font=6):
    """Подбирает максимальный размер шрифта, при котором текст помещается в ячейку.
    Возвращает (font_size, lines, needed_height). needed_height может быть больше max_height, если не влезает."""
    for font_size in range(max_font, min_font - 1, -1):
        lines = split_lines(text, font_size, max_width)
        total_height = len(lines) * font_size * 1.2
        if total_height <= max_height:
            return font_size, lines, total_height
    # Даже минимальный шрифт не помещается – используем его, но возвращаем реальную высоту
    lines = split_lines(text, min_font, max_width)
    total_height = len(lines) * min_font * 1.2
    return min_font, lines, total_height

def draw_text_box(page, text, x0, y0, max_width, max_height, font_path, color=(0,0,0)):
    """Рисует текст в ячейке, подбирая шрифт.
    Возвращает реально занятую высоту (может быть больше max_height)."""
    if not text.strip():
        return 0
    font_size, lines, needed_height = fit_text_to_cell(text, max_width, max_height, font_path)
    line_h = font_size * 1.2
    total_h = len(lines) * line_h
    # Центрируем по вертикали (даже если needed_height > max_height, центрируем в пределах max_height)
    y = y0 + (max_height - total_h) / 2
    if y < y0:
        y = y0
    for line in lines:
        if font_path:
            page.insert_text((x0, y), line, fontsize=font_size, fontname="Arial", fontfile=font_path, color=color)
        else:
            page.insert_text((x0, y), line, fontsize=font_size, fontname="helv", color=color)
        y += line_h
    return total_h

def main():
    parser = argparse.ArgumentParser(description="Generate PDF with auto font scaling and row height adjustment")
    parser.add_argument("--json", required=True, help="JSON file with blocks")
    parser.add_argument("--output", "-o", default="output_from_json.pdf", help="Output PDF path")
    parser.add_argument("--max-font", type=int, default=12, help="Maximum font size for table cells (default 12)")
    parser.add_argument("--min-font", type=int, default=6, help="Minimum font size for table cells (default 6)")
    args = parser.parse_args()

    with open(args.json, 'r', encoding='utf-8') as f:
        data = json.load(f)

    input_pdf = data.get("input_file")
    if not input_pdf or not Path(input_pdf).exists():
        logger.error(f"Input PDF not found: {input_pdf}")
        return

    doc = fitz.open(input_pdf)
    blocks = data["blocks"]
    blocks_sorted = sorted(blocks, key=lambda b: (b["page_number"], b["bbox"]["y0"]))

    # --- Удаляем оригинальный текст в нетейблицах ---
    for block in blocks_sorted:
        if block["type"] == "table":
            continue
        page_num = block["page_number"] - 1
        page = doc[page_num]
        rect = fitz.Rect(block["bbox"]["x0"]-2, block["bbox"]["y0"]-2,
                         block["bbox"]["x1"]+2, block["bbox"]["y1"]+2)
        page.add_redact_annot(rect, fill=None)
    for page_num in range(len(doc)):
        doc[page_num].apply_redactions()

    font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
    if not Path(font_path).exists():
        font_path = None
        logger.warning("Arial.ttf not found, Cyrillic may not render")

    # --- Вставка текста и таблиц ---
    for block in blocks_sorted:
        page_num = block["page_number"] - 1
        page = doc[page_num]

        if block["type"] == "table" and block.get("table_data"):
            cells = block["table_data"].get("cells", []) if isinstance(block["table_data"], dict) else []
            if not cells:
                continue

            # Сначала для каждой строки вычислим необходимую максимальную высоту (с учётом текста и минимального шрифта)
            row_original_heights = []
            row_needed_heights = []
            for row in cells:
                max_orig_h = 0
                max_needed_h = 0
                for cell in row:
                    bbox = cell.get("bbox")
                    if not bbox:
                        continue
                    h_orig = bbox["y1"] - bbox["y0"]
                    max_orig_h = max(max_orig_h, h_orig)
                    text = cell.get("text", "")
                    if text.strip():
                        # Оцениваем нужную высоту при минимальном шрифте (чтобы понять, требуется ли растягивать строку)
                        cell_width = bbox["x1"] - bbox["x0"]
                        _, _, needed_h = fit_text_to_cell(text, cell_width-4, h_orig, font_path, max_font=args.max_font, min_font=args.min_font)
                        max_needed_h = max(max_needed_h, needed_h)
                row_original_heights.append(max_orig_h)
                row_needed_heights.append(max(max_needed_h, max_orig_h))

            # Рисуем ячейки, смещая строки вниз, если нужно
            current_y_offset = 0
            for i, row in enumerate(cells):
                original_y0 = row[0]["bbox"]["y0"] if row else 0
                new_y0 = original_y0 + current_y_offset
                # Определяем высоту, которую будем использовать для этой строки (макс из оригинальной и необходимой)
                actual_row_height = max(row_original_heights[i], row_needed_heights[i])
                # Рисуем каждую ячейку строки
                for cell in row:
                    text = cell.get("text", "")
                    bbox = cell.get("bbox")
                    if not bbox or not text.strip():
                        continue
                    x0, y0_orig, x1, y1_orig = bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]
                    cell_width = x1 - x0
                    # Используем актуальную высоту строки для рисования текста
                    draw_text_box(page, text, x0+2, new_y0, cell_width-4, actual_row_height, font_path)
                # Смещение для следующей строки
                delta = actual_row_height - (y1_orig - y0_orig)
                if delta > 0:
                    current_y_offset += delta
        else:
            # Обычный текст (без изменений)
            text = block.get("text", "")
            if not text:
                continue
            bbox = block["bbox"]
            font_size = block.get("font_size", 12)
            block_width = bbox["x1"] - bbox["x0"]
            block_height = bbox["y1"] - bbox["y0"]
            lines = split_lines(text, font_size, block_width)
            line_h = font_size * 1.2
            total_h = len(lines) * line_h
            y = bbox["y0"] if total_h <= block_height else bbox["y0"]
            for line in lines:
                if font_path:
                    page.insert_text((bbox["x0"], y), line, fontsize=font_size, fontname="Arial", fontfile=font_path)
                else:
                    page.insert_text((bbox["x0"], y), line, fontsize=font_size, fontname="helv")
                y += line_h

    doc.save(args.output)
    doc.close()
    logger.info(f"Generated PDF saved to {args.output}")

if __name__ == "__main__":
    main()