#!/usr/bin/env python
"""
PDF Technical Translator - CLI entry point
"""
import argparse
import json
import sys
from pathlib import Path
from tqdm import tqdm
from loguru import logger

from src.services.pdf_parser_service import PDFParserService
from src.services.translation_service import TranslationService
from src.services.pdf_generator_service import PDFGeneratorService
from src.services.table_processor_service import TableProcessorService

def load_glossary(glossary_path: str):
    """Load glossary from JSON file."""
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
    parser.add_argument("--glossary", "-g", help="JSON file with glossary (key: original term, value: translation)")
    parser.add_argument("--model", default="llama-3.3-70b-versatile", help="Groq model name")
    parser.add_argument("--no-cache", action="store_true", help="Disable Redis cache (if set)")
    args = parser.parse_args()

    # Validate input file
    if not Path(args.input).exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    # Load glossary
    glossary = load_glossary(args.glossary) if args.glossary else None
    if glossary:
        logger.info(f"Loaded glossary with {len(glossary)} terms")

    # Step 1: Parse PDF
    logger.info(f"Parsing PDF: {args.input}")
    parser_svc = PDFParserService()
    blocks = parser_svc.extract_blocks(args.input)
    logger.info(f"Extracted {len(blocks)} blocks (including tables)")

    # Step 2: Translate
    translator = TranslationService(model=args.model)
    if args.no_cache:
        translator.cache.client = None  # disable cache
        logger.info("Cache disabled")

    # Pre-process tables
    table_processor = TableProcessorService(translator)
    # Prepare translated_texts list
    translated_texts = [""] * len(blocks)
    non_table_indices = []
    table_indices = []

    for i, block in enumerate(blocks):
        if block.type == "table" and block.table_data:
            table_indices.append(i)
        else:
            non_table_indices.append(i)

    # Translate tables with progress bar
    if table_indices:
        logger.info(f"Translating {len(table_indices)} tables...")
        for idx in tqdm(table_indices, desc="Tables", unit="table"):
            block = blocks[idx]
            translated_table = table_processor.translate_table(
                block.table_data, args.src_lang, args.tgt_lang, glossary
            )
            blocks[idx].table_data = translated_table
            # translated_texts[idx] remains empty (tables have no text translation)

    # Translate text blocks with progress bar
    if non_table_indices:
        non_table_blocks = [blocks[i] for i in non_table_indices]
        logger.info(f"Translating {len(non_table_blocks)} text blocks...")
        # We'll use translate_blocks but with progress inside? Better to modify translate_blocks to accept callback.
        # For simplicity, we call translate_blocks and wrap it with tqdm manually.
        # But translate_blocks already iterates. We'll modify TranslationService to support progress reporting.
        # Alternatively, we can call translation per block with progress.
        # Let's do per-block call to show progress (slightly less efficient but fine).
        translations = []
        for i, block in enumerate(tqdm(non_table_blocks, desc="Text blocks", unit="block")):
            # Use translate_blocks for single block? We'll create a helper.
            # We'll use existing translate_blocks but with list of one element.
            # But to avoid extra overhead, let's call _call_groq directly? Better keep translation logic.
            # We'll reuse translate_blocks by passing a single block list.
            trans = translator.translate_blocks([block], args.src_lang, args.tgt_lang, glossary)
            translations.append(trans[0])
        # Assign translations to correct indices
        for idx, trans in zip(non_table_indices, translations):
            translated_texts[idx] = trans

    # Step 3: Generate PDF
    logger.info(f"Generating PDF: {args.output}")
    generator = PDFGeneratorService()
    generator.generate_pdf(args.output, blocks, translated_texts)
    logger.success(f"Done! Output saved to {args.output}")

if __name__ == "__main__":
    main()