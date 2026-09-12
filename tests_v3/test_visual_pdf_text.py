from __future__ import annotations

import pymupdf

from synthex_platform.visual.ingestion import pdf_text


def _pdf(path, text: str = ""):
    document = pymupdf.open()
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_good_pypdf_page_is_retained(tmp_path):
    path = tmp_path / "text.pdf"
    _pdf(path, "This page contains sufficient native PDF text for extraction validation.")
    result = pdf_text.extract_pdf_pages(path)
    assert result[0].parser == "pypdf"
    assert result[0].sufficient is True
    assert result[0].ocr_needed is False


def test_weak_pypdf_page_uses_pymupdf(monkeypatch, tmp_path):
    path = tmp_path / "fallback.pdf"
    _pdf(path, "PyMuPDF should recover this sufficiently long page of native source text.")
    monkeypatch.setattr(pdf_text, "_pypdf_texts", lambda _: ([""], [None]))
    result = pdf_text.extract_pdf_pages(path)
    assert result[0].parser == "pymupdf"
    assert result[0].sufficient is True
    assert result[0].ocr_needed is False


def test_empty_native_page_is_marked_for_future_ocr(tmp_path):
    path = tmp_path / "empty.pdf"
    _pdf(path)
    result = pdf_text.extract_pdf_pages(path)
    assert result[0].parser == "pymupdf"
    assert result[0].sufficient is False
    assert result[0].ocr_needed is True
    assert "normalized_text_below_minimum" in result[0].insufficiency_reasons
