"""Opt-in OCR fallback for visually scanned pages only."""

from .pipeline import extract_pages_with_ocr
from .tesseract import PyMuPDFTesseractProvider, diagnose_tesseract

__all__ = ["PyMuPDFTesseractProvider", "diagnose_tesseract", "extract_pages_with_ocr"]
