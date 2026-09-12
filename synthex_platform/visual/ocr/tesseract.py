"""PyMuPDF-backed Tesseract provider and Windows-friendly diagnostic utility."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pymupdf

from synthex_platform.visual.models import OCRPageResult, OCRQualityReport, OCRTextBlock, VisualProvenance
from .providers import OCRProvider
from .quality import normalize_ocr_text


DEFAULT_OCR_DPI = 300


def diagnose_tesseract(language: str = "eng") -> dict[str, object]:
    executable = shutil.which("tesseract")
    tessdata = os.getenv("TESSDATA_PREFIX")
    version = None
    if executable:
        try:
            version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5, check=False).stdout.splitlines()[0]
        except (OSError, subprocess.SubprocessError):
            pass
    return {"available": bool(executable and tessdata), "provider": "pymupdf_tesseract", "engine": "tesseract",
            "executable": executable, "engine_version": version, "language": language, "tessdata_path": tessdata,
            "language_data_available": bool(tessdata and Path(tessdata).exists())}


class PyMuPDFTesseractProvider(OCRProvider):
    provider_name = "pymupdf_tesseract"

    def recognize_page(self, pdf_path: str | Path, page: int, source_id: str | None, language: str = "eng", dpi: int = DEFAULT_OCR_DPI) -> OCRPageResult:
        diagnostic = diagnose_tesseract(language)
        provenance = VisualProvenance(origin="ocr_extracted", source_id=source_id, page=page, object_type="ocr_block", parser_or_method=self.provider_name, verification_status="extracted")
        if not diagnostic["available"]:
            return OCRPageResult(source_id=source_id, page=page, engine="tesseract", language=language, dpi=dpi,
                quality=OCRQualityReport(status="unavailable", warnings=["Tesseract executable or TESSDATA_PREFIX is unavailable; OCR was not attempted."], engine_version=diagnostic["engine_version"]), provenance=provenance)
        try:
            with pymupdf.open(str(pdf_path)) as document:
                page_object = document[page - 1]
                # Keep the Page alive while its TextPage is consumed. PyMuPDF's
                # OCR TextPage holds a weak reference to this object.
                textpage = page_object.get_textpage_ocr(language=language, dpi=dpi, full=True, tessdata=diagnostic["tessdata_path"])
                raw = page_object.get_text("text", textpage=textpage)
        except Exception as exc:
            return OCRPageResult(source_id=source_id, page=page, engine="tesseract", language=language, dpi=dpi,
                quality=OCRQualityReport(status="failed", warnings=[f"OCR failed: {type(exc).__name__}"], engine_version=diagnostic["engine_version"]), provenance=provenance)
        normalized = normalize_ocr_text(raw)
        return OCRPageResult(source_id=source_id, page=page, engine="tesseract", language=language, dpi=dpi, raw_text=raw, normalized_text=normalized,
            blocks=[OCRTextBlock(raw_text=raw, normalized_text=normalized)] if raw else [], quality=OCRQualityReport(status="succeeded", engine_version=diagnostic["engine_version"]),
            provenance=provenance.model_copy(update={"raw_text": raw, "normalized_text": normalized}))
