"""Per-page native PDF extraction without changing legacy ingestion behavior."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, Field
from pypdf import PdfReader


MIN_ALPHANUMERIC_CHARACTERS = 20
MIN_NORMALIZED_CHARACTERS = 40
MAX_REPLACEMENT_CHARACTER_RATIO = 0.02


class TextSufficiency(BaseModel):
    sufficient: bool
    reasons: list[str] = Field(default_factory=list)


class PageTextResult(BaseModel):
    page: int = Field(ge=1)
    text: str = ""
    parser: Literal["pypdf", "pymupdf", "ocr", "none"] = "none"
    sufficient: bool = False
    insufficiency_reasons: list[str] = Field(default_factory=list)
    ocr_needed: bool = False
    attempt_history: list[str] = Field(default_factory=list)


def is_text_sufficient(text: str | None) -> TextSufficiency:
    """Evaluate native text deterministically, without making scientific claims."""
    text = text or ""
    normalized = re.sub(r"\s+", " ", text).strip()
    reasons: list[str] = []
    if len(normalized) < MIN_NORMALIZED_CHARACTERS:
        reasons.append("normalized_text_below_minimum")
    if sum(char.isalnum() for char in normalized) < MIN_ALPHANUMERIC_CHARACTERS:
        reasons.append("alphanumeric_text_below_minimum")
    if normalized and normalized.count("\ufffd") / len(normalized) > MAX_REPLACEMENT_CHARACTER_RATIO:
        reasons.append("replacement_character_ratio_exceeded")
    return TextSufficiency(sufficient=not reasons, reasons=reasons)


def _pypdf_texts(pdf_path: str | Path) -> tuple[list[str | None], list[str | None]]:
    try:
        reader = PdfReader(str(pdf_path))
        return [page.extract_text() or "" for page in reader.pages], [None] * len(reader.pages)
    except Exception as exc:
        # A complete reader failure is represented for every page by the PyMuPDF pass.
        try:
            import pymupdf
            with pymupdf.open(str(pdf_path)) as document:
                return [None] * len(document), [type(exc).__name__] * len(document)
        except Exception:
            return [None], [type(exc).__name__]


def _pymupdf_text(pdf_path: str | Path, page_index: int) -> str:
    import pymupdf

    with pymupdf.open(str(pdf_path)) as document:
        return document[page_index].get_text("text") or ""


def extract_pdf_pages(pdf_path: str | Path) -> list[PageTextResult]:
    """Extract every page through PyPDF, then PyMuPDF only when needed.

    This intentionally does not call the frozen V2/battery utility.  A page that
    remains insufficient is surfaced for a future OCR stage rather than OCR'd.
    """
    texts, errors = _pypdf_texts(pdf_path)
    results: list[PageTextResult] = []
    for index, text in enumerate(texts):
        initial = is_text_sufficient(text)
        if text is not None and initial.sufficient:
            results.append(PageTextResult(page=index + 1, text=text, parser="pypdf", sufficient=True, attempt_history=["pypdf"]))
            continue
        try:
            fallback_text = _pymupdf_text(pdf_path, index)
            fallback = is_text_sufficient(fallback_text)
            reasons = fallback.reasons
            if errors[index]:
                reasons = [f"pypdf_error:{errors[index]}", *reasons]
            results.append(PageTextResult(
                page=index + 1, text=fallback_text, parser="pymupdf",
                sufficient=fallback.sufficient, insufficiency_reasons=reasons,
                ocr_needed=not fallback.sufficient, attempt_history=["pypdf", "pymupdf"],
            ))
        except Exception as exc:
            reasons = [*initial.reasons, f"pymupdf_error:{type(exc).__name__}"]
            if errors[index]:
                reasons.insert(0, f"pypdf_error:{errors[index]}")
            results.append(PageTextResult(
                page=index + 1, text="", parser="none", sufficient=False,
                insufficiency_reasons=reasons, ocr_needed=True, attempt_history=["pypdf", "pymupdf"],
            ))
    return results
