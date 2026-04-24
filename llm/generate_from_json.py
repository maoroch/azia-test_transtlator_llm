#!/usr/bin/env python
import json
import argparse
import fitz  # PyMuPDF
from pathlib import Path
from loguru import logger

def split_text(text, font_size, max_width):
    words = text.split()
    lines = []
    cur = []
    for w in words:
        test = ' '.join(cur + [w])
        if len(test) * font_size * 0.6 <= max_width:
            cur.append(w)
        else:
            if cur:
                lines.append(' '.join(cur))
            cur = [w]
    if cur:
        lines.append(' '.join(cur))
    return lines if lines else [text]

def main():
    parser = argparse.ArgumentParser(description="Generate PDF from exported JSON")
    parser.add_argument("--json", required=True)
    parser.add_argument("--output", "-o", default="output_from_json.pdf")
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

    # Удаляем оригинальный текст в областях (опционально)
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

    # Вставка текста и таблиц
    for block in blocks_sorted:
        page_num = block["page_number"] - 1
        page = doc[page_num]

        if block["type"] == "table" and block.get("table_data"):
            # Отрисовка таблицы по ячейкам
            cells = block["table_data"].get("cells", []) if isinstance(block["table_data"], dict) else []
            for row in cells:
                for cell in row:
                    text = cell.get("text", "")
                    if not text.strip():
                        continue
                    bbox = cell.get("bbox")
                    if not bbox:
                        continue
                    font_size = 10
                    x0, y0, x1, y1 = bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]
                    block_width = x1 - x0
                    lines = split_text(text, font_size, block_width)
                    line_h = font_size * 1.2
                    y_cursor = y0 + 2
                    for line in lines:
                        if font_path:
                            page.insert_text((x0+2, y_cursor), line, fontsize=font_size, fontname="Arial", fontfile=font_path)
                        else:
                            page.insert_text((x0+2, y_cursor), line, fontsize=font_size, fontname="helv")
                        y_cursor += line_h
        else:
            # Обычный текст
            text = block.get("text", "")
            if not text:
                continue
            bbox = block["bbox"]
            font_size = block.get("font_size", 12)
            block_width = bbox["x1"] - bbox["x0"]
            lines = split_text(text, font_size, block_width)
            line_h = font_size * 1.2
            y_cursor = bbox["y0"]
            for line in lines:
                if font_path:
                    page.insert_text((bbox["x0"], y_cursor), line, fontsize=font_size, fontname="Arial", fontfile=font_path)
                else:
                    page.insert_text((bbox["x0"], y_cursor), line, fontsize=font_size, fontname="helv")
                y_cursor += line_h

    doc.save(args.output)
    doc.close()
    logger.info(f"Generated PDF saved to {args.output}")

if __name__ == "__main__":
    main()