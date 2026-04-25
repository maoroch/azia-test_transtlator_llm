from src.services.pdf_parser_service import PDFParserService
import pdfplumber
from src.services.translation_service import TranslationService
from src.services.pdf_generator_service import PDFGeneratorService
from src.services.table_processor_service import TableProcessorService

# Диагностика (можно оставить)
with pdfplumber.open("sample.pdf") as pdf:
    page = pdf.pages[0]
    print("=== extract_words() ===")
    words = page.extract_words()
    print(words)
    print("=== extract_text() ===")
    text = page.extract_text()
    print(text)
    print("=== chars count ===")
    print(len(page.chars))
    if page.chars:
        print("first char keys:", page.chars[0].keys())
        print("first char sample:", page.chars[0])

if __name__ == "__main__":
    # 1. Парсим PDF
    parser = PDFParserService()
    blocks = parser.extract_blocks("sample.pdf")

    # 2. Инициализируем переводчик и глоссарий
    translator = TranslationService()
    glossary = {"PID": "ПИД-регулятор", "PLC": "программируемый логический контроллер", "HMI": "человеко-машинный интерфейс"}

    # 3. Обработка таблиц (если есть)
    table_processor = TableProcessorService(translator)
    for i, block in enumerate(blocks):
        if block.type == "table" and block.table_data:
            translated_table = table_processor.translate_table(block.table_data, "en", "ru", glossary)
            blocks[i].table_data = translated_table

    # 4. Переводим только не-табличные блоки
    translated_texts = [""] * len(blocks)
    non_table_indices = [i for i, b in enumerate(blocks) if b.type != "table"]
    non_table_blocks = [blocks[i] for i in non_table_indices]
    if non_table_blocks:
        non_table_translations = translator.translate_blocks(non_table_blocks, src_lang="en", tgt_lang="ru", glossary=glossary)
        for idx, trans in zip(non_table_indices, non_table_translations):
            translated_texts[idx] = trans


    if non_table_indices:
        non_table_blocks = [blocks[i] for i in non_table_indices]
        logger.info(f"Translating {len(non_table_blocks)} text blocks using page grouping (one request per page chunk)...")
        translations = translator.translate_by_pages(
            non_table_blocks, args.src_lang, args.tgt_lang, glossary,
            max_blocks_per_req=args.batch_size
        )
        for idx, trans in zip(non_table_indices, translations):
            translated_texts[idx] = trans
        logger.info("Page-grouped translation completed")


    # 5. Выводим в консоль
    for original, translated in zip(blocks, translated_texts):
        if original.type == "table":
            print(f"Таблица на стр. {original.page_number} (переведена)")
        else:
            print(f"Оригинал: {original.text}")
            print(f"Перевод: {translated}\n")

    # 6. Генерируем PDF
    generator = PDFGeneratorService()
    generator.generate_pdf("output_translated.pdf", blocks, translated_texts)
    print("PDF создан: output_translated.pdf")