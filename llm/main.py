from src.services.pdf_parser_service import PDFParserService
import pdfplumber
from src.services.translation_service import TranslationService
from src.services.pdf_generator_service import PDFGeneratorService

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
    # Парсим PDF
    parser = PDFParserService()
    blocks = parser.extract_blocks("sample.pdf")
    
    # Переводим
    translator = TranslationService()
    glossary = {"PID": "ПИД-регулятор", "PLC": "программируемый логический контроллер", "HMI": "человеко-машинный интерфейс"}
    translated_texts = translator.translate_blocks(blocks, src_lang="en", tgt_lang="ru", glossary=glossary)
    
    # Выводим в консоль
    for original, translated in zip(blocks, translated_texts):
        print(f"Оригинал: {original.text}")
        print(f"Перевод: {translated}\n")
    
    # Генерируем PDF
    generator = PDFGeneratorService()
    generator.generate_pdf("output_translated.pdf", blocks, translated_texts)
    print("PDF создан: output_translated.pdf")
