"""Native-text-first OCR orchestration for only insufficient PDF pages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from synthex_platform.visual.ingestion.pdf_text import PageTextResult, extract_pdf_pages, is_text_sufficient
from synthex_platform.visual.models import OCRPageResult
from .providers import OCRProvider
from .tesseract import DEFAULT_OCR_DPI


@dataclass
class OCRIngestionResult:
    pages: list[PageTextResult]
    ocr_blocks: list[OCRPageResult]


def extract_pages_with_ocr(pdf_path: str | Path, source_id: str | None, provider: OCRProvider, *, language: str = "eng", dpi: int = DEFAULT_OCR_DPI) -> OCRIngestionResult:
    pages = extract_pdf_pages(pdf_path)
    blocks: list[OCRPageResult] = []
    for index, result in enumerate(pages):
        if not result.ocr_needed:
            continue
        ocr = provider.recognize_page(pdf_path, result.page, source_id, language, dpi)
        blocks.append(ocr)
        history = [*result.attempt_history, "ocr"]
        if ocr.quality.status == "succeeded" and is_text_sufficient(ocr.raw_text).sufficient:
            pages[index] = result.model_copy(update={"text": ocr.raw_text, "parser": "ocr", "sufficient": True, "ocr_needed": False, "insufficiency_reasons": [], "attempt_history": history})
        else:
            reason = f"ocr_{ocr.quality.status}"
            pages[index] = result.model_copy(update={"attempt_history": history, "insufficiency_reasons": [*result.insufficiency_reasons, reason], "ocr_needed": True})
    return OCRIngestionResult(pages=pages, ocr_blocks=blocks)
