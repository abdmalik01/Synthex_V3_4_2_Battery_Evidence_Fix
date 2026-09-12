from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from synthex_platform.visual.document import build_visual_document
from synthex_platform.visual.ingestion.pdf_text import PageTextResult
from synthex_platform.visual.models import BoundingBox, OCRPageResult, OCRQualityReport, OCRTextBlock, VisualDocument, VisualProvenance
from synthex_platform.visual.ocr import diagnose_tesseract
from synthex_platform.visual.ocr.pipeline import extract_pages_with_ocr
from synthex_platform.visual.ocr.providers import OCRProvider
from synthex_platform.visual.ocr.quality import normalize_ocr_text
from synthex_platform.visual.verification import classify_evidence_strength


FIXTURE = Path(__file__).parent / "fixtures" / "visual" / "ocr_scanned_text.json"


def _image_only_pdf(path):
    # Rasterize text into an image, so both native PDF text paths intentionally fail.
    source = pymupdf.open()
    page = source.new_page()
    page.insert_text((72, 72), "Li2FeTiO4 cathode; 700 C; 121.3 mAh/g")
    pixmap = page.get_pixmap()
    source.close()
    document = pymupdf.open()
    page = document.new_page()
    page.insert_image(page.rect, stream=pixmap.tobytes("png"))
    document.save(path)
    document.close()


class FakeOCRProvider(OCRProvider):
    provider_name = "fake_ocr"

    def __init__(self, status="succeeded"):
        self.status, self.calls = status, []

    def recognize_page(self, pdf_path, page, source_id, language, dpi):
        self.calls.append((page, dpi))
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))["raw_text"] if self.status == "succeeded" else ""
        provenance = VisualProvenance(origin="ocr_extracted", source_id=source_id, page=page, object_type="ocr_block", parser_or_method=self.provider_name, raw_text=raw)
        return OCRPageResult(source_id=source_id, page=page, engine="fake", language=language, dpi=dpi, raw_text=raw,
            normalized_text=normalize_ocr_text(raw), blocks=[OCRTextBlock(raw_text=raw, normalized_text=normalize_ocr_text(raw), bbox=BoundingBox(x0=1, y0=2, x1=3, y1=4))] if raw else [],
            quality=OCRQualityReport(status=self.status), provenance=provenance)


def test_native_good_page_does_not_invoke_ocr(tmp_path):
    path = tmp_path / "native.pdf"
    document = pymupdf.open(); page = document.new_page(); page.insert_text((72, 72), "This page has enough native text to avoid an OCR fallback invocation entirely."); document.save(path); document.close()
    provider = FakeOCRProvider()
    result = extract_pages_with_ocr(path, "src-native", provider)
    assert provider.calls == [] and result.ocr_blocks == [] and result.pages[0].parser == "pypdf"


def test_scanned_page_invokes_fake_ocr_and_preserves_history_and_symbols(tmp_path):
    path = tmp_path / "scanned.pdf"
    _image_only_pdf(path)
    provider = FakeOCRProvider()
    result = extract_pages_with_ocr(path, "src-scan", provider, dpi=320)
    page, ocr = result.pages[0], result.ocr_blocks[0]
    assert provider.calls == [(1, 320)]
    assert page.parser == "ocr" and page.attempt_history == ["pypdf", "pymupdf", "ocr"]
    assert ocr.provenance.origin == "ocr_extracted" and ocr.blocks[0].bbox is not None
    assert "1.096 × 10⁻¹² cm²/s" in ocr.raw_text and "Fe³⁺" in ocr.raw_text
    assert "Li2FeTiO4" in ocr.raw_text
    assert classify_evidence_strength(ocr.provenance, True) == "verified_ocr"


def test_unavailable_provider_and_native_fallback_history(monkeypatch, tmp_path):
    path = tmp_path / "scanned.pdf"
    _image_only_pdf(path)
    unavailable = FakeOCRProvider("unavailable")
    result = extract_pages_with_ocr(path, "src-unavailable", unavailable)
    assert result.pages[0].ocr_needed and "ocr_unavailable" in result.pages[0].insufficiency_reasons
    assert result.ocr_blocks[0].quality.status == "unavailable"

    from synthex_platform.visual.ocr import pipeline
    monkeypatch.setattr(pipeline, "extract_pdf_pages", lambda _: [PageTextResult(page=1, text="native fallback text that is sufficient for this test page", parser="pymupdf", sufficient=True, attempt_history=["pypdf", "pymupdf"])])
    provider = FakeOCRProvider()
    assert extract_pages_with_ocr(path, "src-fallback", provider).ocr_blocks == []
    assert provider.calls == []


def test_sidecar_ocr_roundtrip_no_duplicate_and_old_compatibility(tmp_path):
    path = tmp_path / "scanned.pdf"
    _image_only_pdf(path)
    provider = FakeOCRProvider()
    document = build_visual_document(path, "src-sidecar", ocr_provider=provider, ocr_dpi=280)
    assert len(document.ocr_blocks) == 1 and document.ocr_blocks[0].dpi == 280
    restored = VisualDocument.model_validate_json(document.model_dump_json())
    assert len(restored.ocr_blocks) == 1
    old = document.model_dump(); old.pop("ocr_blocks")
    assert VisualDocument.model_validate(old).ocr_blocks == []


def test_diagnostic_is_explicit_about_current_tesseract_availability():
    diagnostic = diagnose_tesseract()
    assert diagnostic["provider"] == "pymupdf_tesseract"
    assert "available" in diagnostic and "language_data_available" in diagnostic
