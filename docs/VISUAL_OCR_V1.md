# Visual OCR Fallback V1

Native text is always preferred: PyPDF, then PyMuPDF, then OCR only for pages
that still fail the shared Stage 1 text-sufficiency check. OCR never runs for
a page with sufficient native text.

OCR is optional. The built-in provider uses PyMuPDF's Tesseract integration and
expects a locally installed Tesseract executable plus `TESSDATA_PREFIX` pointing
to tessdata. On Windows, install Tesseract separately, set `TESSDATA_PREFIX`,
and use `diagnose_tesseract()` to check executable, version, and language-data
visibility. Synthex does not install or download OCR engines.

OCR output is stored only in visual sidecars as `origin=ocr_extracted`, with raw
and conservatively normalized text kept separately. It is not native evidence,
does not become a canonical measurement, and verified OCR evidence is classified
as `verified_ocr`, never `verified_native`. Chemical formulas, units, symbols,
and numeric values are never guessed or repaired.
