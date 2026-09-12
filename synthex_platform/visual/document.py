"""Build deterministic visual-source documents without touching archives."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from .ingestion.pdf_text import extract_pdf_pages
from .models import VisualDocument, VisualPage
from .tables.pymupdf_extractor import extract_tables
from .figures.candidates import detect_figure_candidates


def source_checksum(pdf_path: str | Path) -> str:
    return sha256(Path(pdf_path).read_bytes()).hexdigest()


def build_visual_document(pdf_path: str | Path, source_id: str, include_figures: bool = False, ocr_provider=None, ocr_language: str = "eng", ocr_dpi: int = 300) -> VisualDocument:
    """Create a sidecar-ready document from native extraction results only."""
    ocr_blocks = []
    if ocr_provider is None:
        page_results = extract_pdf_pages(pdf_path)
    else:
        from .ocr.pipeline import extract_pages_with_ocr
        ocr_result = extract_pages_with_ocr(pdf_path, source_id, ocr_provider, language=ocr_language, dpi=ocr_dpi)
        page_results, ocr_blocks = ocr_result.pages, ocr_result.ocr_blocks
    pages = [VisualPage(
        page=result.page, text_parser=result.parser, text_sufficient=result.sufficient,
        ocr_needed=result.ocr_needed, warnings=result.insufficiency_reasons,
    ) for result in page_results]
    return VisualDocument(
        source_id=source_id,
        source_checksum=source_checksum(pdf_path),
        extraction_metadata={"table_parser": "pymupdf", "text_extraction": "pypdf_then_pymupdf_v1"},
        pages=pages,
        tables=extract_tables(pdf_path, source_id=source_id),
        figures=detect_figure_candidates(pdf_path, source_id=source_id) if include_figures else [],
        ocr_blocks=ocr_blocks,
    )
