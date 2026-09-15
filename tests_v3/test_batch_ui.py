from pathlib import Path

import pytest

from synthex_platform.batch import MAX_BATCH_PAPERS, MIN_RESEARCH_BATCH, validate_batch_size


def test_batch_capacity_supports_at_least_ten_papers():
    assert MIN_RESEARCH_BATCH >= 10
    assert MAX_BATCH_PAPERS >= MIN_RESEARCH_BATCH
    validate_batch_size(10)
    validate_batch_size(MAX_BATCH_PAPERS)


def test_batch_size_rejects_empty_and_over_limit():
    with pytest.raises(ValueError):
        validate_batch_size(0)
    with pytest.raises(ValueError):
        validate_batch_size(MAX_BATCH_PAPERS + 1)


def test_primary_streamlit_ui_enables_multiple_pdf_uploads():
    text = Path("platform_app.py").read_text(encoding="utf-8")
    assert "accept_multiple_files=True" in text
    assert "synthex_batch_archives" in text
    assert "combined_result_rows" in text
    assert "Extract {len(uploaded_files)} papers" in text
