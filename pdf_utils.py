"""Compatibility PDF utilities for the original Synthex layout."""
from pathlib import Path
from synthex_v2.pdf_utils_v2 import extract_pages, pages_to_marked_text


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    return pages_to_marked_text(extract_pages(pdf_path))
