#!/usr/bin/env python
import argparse
import json
import sys
from pathlib import Path
from tqdm import tqdm
from loguru import logger

from src.services.pdf_parser_service import PDFParserService
from src.services.translation_service import TranslationService      # Groq
from src.services.ollama_service import OllamaTranslationService   # Ollama
from src.services.pdf_generator_service import PDFGeneratorService
from src.services.table_processor_service import TableProcessorService

def load_glossary(glossary_path: str):
    if not glossary_path:
        return None
    with open(glossary_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def main():
    parser = argparse.ArgumentParser(description="Translate technical PDF preserving layout")
    parser.add_argument("--input", "-i", required=True, help="Input PDF file path")
    parser.add_argument("--output", "-o", default="output_translated.pdf", help="Output PDF file path")
    parser.add_argument("--src-lang", default="en", help="Source language (default: en)")
    parser.add_argument("--tgt-lang", default="ru", help="Target language (default: ru)")
    parser.add_argument("--glossary", "-g", help="JSON file with glossary")
    parser.add_argument("--model", default="llama3:8b", help="Model name (for Groq or Ollama)")
    parser.add_argument("--backend", choices=["groq", "ollama"], default="ollama", help="Translation backend")
    parser.add_argument("--batch-size", type=int, default=5, help="Number of text blocks per API request")
    parser.add_argument("--max-concurrent", type=int, default=5, help="Max concurrent requests (only for Groq)")
    parser.add_argument("--no-cache", action="store_true", help="Disable Redis cache")
    parser.add_argument("--export-json", help="Export blocks and translations to JSON file")
    parser.add_argument("--no-merge", action="store_true", help="Disable merging of short blocks")

    args = parser.parse_args()

    if not Path(args.input).exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    glossary = load_glossary(args.glossary) if args.glossary else None
    if glossary:
        logger.info(f"Loaded glossary with {len(glossary)} terms")

    # 1. Парсинг PDF
    logger.info(f"Parsing PDF: {args.input}")
    parser_svc = PDFParserService()
    blocks = parser_svc.extract_blocks(args.input)
    logger.info(f"Extracted {len(blocks)} blocks (including tables)")

    if not args.no_merge:
        blocks = PDFParserService._merge_short_blocks(blocks)

    # 2. Выбор бэкенда перевода
    if args.backend == "groq":
        translator = TranslationService(model=args.model)
        if args.no_cache:
            translator.cache.client = None
        # Для Groq rate limiting уже внутри
    else:
        translator = OllamaTranslationService(model=args.model)
        if args.no_cache:
            translator.cache.client = None

    # Подготовка списков
    translated_texts = [""] * len(blocks)
    non_table_indices = [i for i, b in enumerate(blocks) if b.type != "table"]
    table_indices = [i for i, b in enumerate(blocks) if b.type == "table"]

    # Таблицы (переводятся целиком)
    if table_indices:
        logger.info(f"Translating {len(table_indices)} tables...")
        table_processor = TableProcessorService(translator)
        for idx in tqdm(table_indices, desc="Tables", unit="table"):
            block = blocks[idx]
            translated_table = table_processor.translate_table(
                block.table_data, args.src_lang, args.tgt_lang, glossary
            )
            blocks[idx].table_data = translated_table

    # Текстовые блоки с батчингом и прогрессом
    if non_table_indices:
        non_table_blocks = [blocks[i] for i in non_table_indices]
        logger.info(f"Translating {len(non_table_blocks)} text blocks...")
        # Прогресс-бар не может напрямую обернуть асинхронный метод, но мы используем синхронный вызов с прогрессом
        # Поскольку translate_blocks уже внутри делает батчи, прогресс будет только после завершения всех.
        # Можно модифицировать сервис, чтобы он возвращал результаты постепенно, но для простоты оставим так.
        translations = translator.translate_blocks(
            non_table_blocks, args.src_lang, args.tgt_lang, glossary,
            batch_size=args.batch_size
        )
        for idx, trans in zip(non_table_indices, translations):
            translated_texts[idx] = trans
        logger.info("Text translation completed")

    # Экспорт в JSON
    if args.export_json:
        export_data = {
            "input_file": args.input,
            "src_lang": args.src_lang,
            "tgt_lang": args.tgt_lang,
            "glossary": glossary,
            "blocks": []
        }
        for block, trans in zip(blocks, translated_texts):
            export_data["blocks"].append({
                "type": block.type,
                "text": trans,
                "original_text": block.text,
                "page_number": block.page_number,
                "bbox": {
                    "x0": block.bbox.x0,
                    "y0": block.bbox.y0,
                    "x1": block.bbox.x1,
                    "y1": block.bbox.y1
                },
                "font_size": block.font_size,
                "font_name": block.font_name,
                "table_data": block.table_data.dict() if block.table_data else None
            })
        with open(args.export_json, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Exported blocks to {args.export_json}")

    # Генерация PDF
    logger.info(f"Generating PDF: {args.output}")
    generator = PDFGeneratorService()
    generator.generate_pdf(args.input, args.output, blocks, translated_texts)
    logger.success(f"Done! Output saved to {args.output}")

if __name__ == "__main__":
    main()