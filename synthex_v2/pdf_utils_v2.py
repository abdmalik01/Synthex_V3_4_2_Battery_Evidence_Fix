from __future__ import annotations
from pathlib import Path
from pypdf import PdfReader


def extract_pages(pdf_path: str | Path) -> list[dict]:
    """Extract PDF text with PyPDF first and a non-OCR PyMuPDF fallback.

    The parser name is retained per page so downstream archives and benchmark reports
    can audit which path produced the source text.
    """
    primary_error: Exception | None = None
    try:
        reader = PdfReader(str(pdf_path))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append({"page": i, "text": text, "parser": "pypdf"})
        return pages
    except Exception as exc:
        primary_error = exc

    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            f"PyPDF text extraction failed with {type(primary_error).__name__}: {primary_error}. "
            "PyMuPDF fallback is not installed."
        ) from exc

    try:
        with pymupdf.open(str(pdf_path)) as document:
            return [
                {"page": index + 1, "text": page.get_text("text") or "", "parser": "pymupdf"}
                for index, page in enumerate(document)
            ]
    except Exception as fallback_error:
        raise RuntimeError(
            f"PDF text extraction failed with PyPDF ({type(primary_error).__name__}: {primary_error}) "
            f"and PyMuPDF ({type(fallback_error).__name__}: {fallback_error})."
        ) from fallback_error


def pages_to_marked_text(pages: list[dict], max_chars: int = 180_000) -> str:
    chunks, total = [], 0
    for item in pages:
        block = f"\n\n--- PAGE {item['page']} ---\n{item['text']}"
        if total + len(block) > max_chars:
            remaining = max_chars - total
            if remaining > 500:
                chunks.append(block[:remaining])
            break
        chunks.append(block)
        total += len(block)
    return "".join(chunks)
