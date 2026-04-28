import pdfplumber
import re
from typing import List, Tuple
from loguru import logger
from collections import Counter
from ..models.document import Block, BoundingBox, Table


class PDFParserService:

    @staticmethod
    def extract_blocks(pdf_path: str) -> List[Block]:
        all_blocks = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                # 1. Таблицы + их bbox (чтобы исключить из текста)
                table_blocks, table_bboxes = PDFParserService._extract_tables(page, page_num)
                all_blocks.extend(table_blocks)

                # 2. Слова — исключаем попавшие внутрь таблиц
                words = page.extract_words(
                    x_tolerance=3, y_tolerance=3,
                    keep_blank_chars=False, use_text_flow=False,
                )
                if words:
                    words = PDFParserService._filter_table_words(words, table_bboxes)
                    if words:
                        paragraphs = PDFParserService._words_to_paragraphs(words, page_num)
                        classified = PDFParserService._classify_blocks(paragraphs, page)
                        all_blocks.extend(classified)
                else:
                    logger.warning(f"Страница {page_num}: слова не найдены")

        logger.info(f"Извлечено {len(all_blocks)} блоков из {pdf_path}")
        return all_blocks

    # ------------------------------------------------------------------ #
    # ТАБЛИЦЫ                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_tables(page, page_num: int) -> Tuple[List[Block], list]:
        table_blocks: List[Block] = []
        table_bboxes: list = []
        seen: set = set()

        for strat in [
            {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
            {"vertical_strategy": "lines_strict", "horizontal_strategy": "lines_strict"},
        ]:
            try:
                for table in page.find_tables(strat):
                    key = tuple(round(v, 1) for v in table.bbox)
                    if key in seen:
                        continue
                    rows = table.extract()
                    if not rows:
                        continue
                    seen.add(key)
                    table_bboxes.append(table.bbox)

                    cells = PDFParserService._extract_cells(table, page)
                    tb = BoundingBox(x0=table.bbox[0], y0=table.bbox[1],
                                     x1=table.bbox[2], y1=table.bbox[3])
                    table_blocks.append(Block(
                        type="table", text="", original_text="",
                        page_number=page_num, bbox=tb,
                        table_data=Table(
                            data=[[c or "" for c in row] for row in rows],
                            bbox=tb, page_number=page_num, cells=cells,
                        )
                    ))
            except Exception as e:
                logger.debug(f"Table strategy {strat} failed: {e}")

        return table_blocks, table_bboxes

    @staticmethod
    def _extract_cells(table, page) -> list:
        out = []
        for row in table.cells:
            row_out = []
            for cell in row:
                if cell is None:
                    row_out.append({"text": "", "bbox": BoundingBox(x0=0, y0=0, x1=0, y1=0)})
                    continue
                x0, y0, x1, y1 = cell
                try:
                    text = page.within_bbox((x0, y0, x1, y1)).extract_text() or ""
                    text = PDFParserService._clean_text(text)
                except Exception:
                    text = ""
                row_out.append({"text": text, "bbox": BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)})
            if row_out:
                out.append(row_out)
        return out

    @staticmethod
    def _filter_table_words(words: list, table_bboxes: list) -> list:
        if not table_bboxes:
            return words
        result = []
        for w in words:
            cx = (w["x0"] + w["x1"]) / 2
            cy = (w["top"] + w["bottom"]) / 2
            if not any(tx0 <= cx <= tx1 and ty0 <= cy <= ty1
                       for (tx0, ty0, tx1, ty1) in table_bboxes):
                result.append(w)
        return result

    # ------------------------------------------------------------------ #
    # СЛОВА → СТРОКИ → ПАРАГРАФЫ                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _words_to_paragraphs(words: list, page_num: int) -> List[Block]:
        if not words:
            return []

        # Сортируем: top → x0
        words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))

        # Шаг 1: собираем строки (слова с одинаковым top ± 4 pt)
        lines: list = []  # [ [top, bottom, [word, ...]], ... ]
        for w in words:
            merged = False
            for line in reversed(lines):
                if abs(w["top"] - line[0]) <= 4:
                    line[2].append(w)
                    line[1] = max(line[1], w["bottom"])
                    merged = True
                    break
            if not merged:
                lines.append([w["top"], w["bottom"], [w]])

        # Шаг 2: каждая строка → dict с текстом и координатами
        line_dicts = []
        for top, bottom, lw in lines:
            lw_sorted = sorted(lw, key=lambda w: w["x0"])
            # Восстанавливаем пробелы между словами
            parts = []
            prev_x1 = None
            for w in lw_sorted:
                if prev_x1 is not None and w["x0"] - prev_x1 > 1.5:
                    parts.append(" ")
                parts.append(w["text"])
                prev_x1 = w["x1"]
            text = PDFParserService._clean_text("".join(parts))
            if not text:
                continue
            line_dicts.append({
                "text": text,
                "top": top, "bottom": bottom,
                "x0": min(w["x0"] for w in lw_sorted),
                "x1": max(w["x1"] for w in lw_sorted),
            })

        if not line_dicts:
            return []

        # Шаг 3: объединяем строки в параграфы
        avg_h = sum(lb["bottom"] - lb["top"] for lb in line_dicts) / len(line_dicts)
        gap_threshold = avg_h * 1.0  # ratio > 1.0 = new paragraph

        groups: list = [[line_dicts[0]]]
        for lb in line_dicts[1:]:
            gap = lb["top"] - groups[-1][-1]["bottom"]
            if gap > gap_threshold:
                groups.append([lb])
            else:
                groups[-1].append(lb)

        # Шаг 4: группы → Block
        blocks = []
        for grp in groups:
            text = re.sub(r'\s+', ' ', " ".join(lb["text"] for lb in grp)).strip()
            if not text:
                continue
            blocks.append(Block(
                type="paragraph",
                text=text, original_text=text,
                page_number=page_num,
                bbox=BoundingBox(
                    x0=min(lb["x0"] for lb in grp),
                    y0=grp[0]["top"],
                    x1=max(lb["x1"] for lb in grp),
                    y1=grp[-1]["bottom"],
                ),
            ))
        return blocks

    # ------------------------------------------------------------------ #
    # КЛАССИФИКАЦИЯ                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _classify_blocks(blocks: List[Block], page) -> List[Block]:
        chars = page.chars or []
        if not chars:
            return blocks

        all_sizes = [ch["size"] for ch in chars if ch.get("size", 0) > 0]
        avg_size = sum(all_sizes) / len(all_sizes) if all_sizes else 12.0

        for block in blocks:
            in_chars = [
                ch for ch in chars
                if (block.bbox.x0 - 5 <= ch.get("x0", 0) <= block.bbox.x1 + 5
                    and block.bbox.y0 - 5 <= ch.get("top", ch.get("y0", 0)) <= block.bbox.y1 + 5)
            ]
            if not in_chars:
                continue

            sizes = [ch["size"] for ch in in_chars if ch.get("size", 0) > 0]
            block.font_size = sum(sizes) / len(sizes) if sizes else avg_size
            fonts = [ch.get("fontname", "") for ch in in_chars]
            block.font_name = Counter(fonts).most_common(1)[0][0] if fonts else ""

            if block.font_size >= avg_size + 1.5 and len(block.text) < 120:
                block.type = "heading"
            elif block.text and block.text[0] in ("•", "-", "–", "*", "·"):
                block.type = "list"
            else:
                block.type = "paragraph"

        return blocks

    # ------------------------------------------------------------------ #
    # УТИЛИТЫ                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _clean_text(text: str) -> str:
        text = text.replace("\u00ad", "").replace("\xad", "")  # soft hyphen
        text = re.sub(r'(?<=[a-zA-Zа-яА-ЯёЁ])-\s+(?=[a-zA-Zа-яА-ЯёЁ])', '', text)  # перенос
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
