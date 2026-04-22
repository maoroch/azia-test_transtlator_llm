from src.services.pdf_parser_service import PDFParserService
import pdfplumber


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
    parser = PDFParserService()
    blocks = parser.extract_blocks("sample.pdf")
    for b in blocks:
        if b.font_size:
            font_info = f"{b.font_name} ({b.font_size:.1f}pt)"
        else:
            font_info = f"{b.font_name or 'unknown'} (size N/A)"
        print(f"Стр. {b.page_number}: [{b.type}] {b.text[:60]}... | Font: {font_info}")
