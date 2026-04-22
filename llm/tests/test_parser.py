import pytest
from src.services.pdf_parser_service import PDFParserService

def test_extract_blocks():
    parser = PDFParserService()
    # Предполагаем, что в tests/fixtures/ есть test.pdf
    blocks = parser.extract_blocks("tests/fixtures/sample.pdf")
    assert len(blocks) > 0
    assert blocks[0].text
    assert blocks[0].page_number == 1
    assert blocks[0].bbox.x0 >= 0