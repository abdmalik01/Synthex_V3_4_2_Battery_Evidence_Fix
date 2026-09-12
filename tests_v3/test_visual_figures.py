from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from pydantic import ValidationError

from synthex_platform.visual.document import build_visual_document
from synthex_platform.visual.figures.cache import FigureUnderstandingCache
from synthex_platform.visual.figures.candidates import detect_figure_candidates, render_figure_crop
from synthex_platform.visual.figures.providers import FigureUnderstandingProvider, apply_understanding, understand_with_cache
from synthex_platform.visual.models import FigureAnnotation, FigureAxis, FigureLegendEntry, FigureUnderstandingResult, VisualDocument, VisualProvenance
from synthex_platform.visual.sidecar_store import VisualSidecarStore


def _figure_pdf(path: Path, *, caption: bool = True):
    document = pymupdf.open()
    page = document.new_page(width=600, height=500)
    # Two vector panels: line plots, axes, labels, legends, and one explicit annotation.
    for offset, panel in ((70, "(a)"), (300, "(b)")):
        page.draw_line((offset, 270), (offset + 180, 270))
        page.draw_line((offset, 270), (offset, 100))
        page.draw_line((offset + 8, 245), (offset + 60, 210))
        page.draw_line((offset + 60, 210), (offset + 125, 140))
        page.insert_text((offset + 4, 95), panel)
    page.insert_text((125, 292), "Cycle Number")
    page.insert_text((15, 185), "Specific Capacity (mAh/g)")
    page.insert_text((90, 125), "LFTO-700")
    page.insert_text((90, 140), "121.3 mAh/g")
    if caption:
        page.insert_text((70, 320), "Fig. 3. Cycling performance of LFTO samples.")
    document.save(path)
    document.close()


class FakeProvider(FigureUnderstandingProvider):
    provider_name = "fake"
    model_name = "fake-v1"
    calls = 0

    def understand(self, image_png, figure, page_context=None):
        self.calls += 1
        annotation = FigureAnnotation(
            raw_text="121.3 mAh/g", panel="a",
            provenance=VisualProvenance(origin="figure_annotation", source_id=figure.source_id, page=figure.page,
                object_id=figure.figure_id, object_type="figure", panel="a", parser_or_method="fake-v1", raw_text="121.3 mAh/g"),
        )
        return FigureUnderstandingResult(
            figure_type="cycling_performance", axes=[FigureAxis(role="x", raw_label="Cycle Number"), FigureAxis(role="y", raw_label="Specific Capacity (mAh/g)", unit="mAh/g")],
            legend_entries=[FigureLegendEntry(raw_label="LFTO-700")], sample_material_labels=["LFTO-700"], annotations=[annotation],
            scientific_meaning="Capacity is compared across cycling.", confidence=0.8,
        )


def test_deterministic_candidates_caption_panels_and_crop(tmp_path):
    path = tmp_path / "figure.pdf"
    _figure_pdf(path)
    first = detect_figure_candidates(path, "src-fig")
    second = detect_figure_candidates(path, "src-fig")
    assert len(first) == 1
    figure = first[0]
    assert figure.figure_id == second[0].figure_id
    assert figure.figure_number == "3"
    assert figure.caption == "Fig. 3. Cycling performance of LFTO samples."
    assert figure.bbox is not None
    assert {panel.label for panel in figure.panels} == {"a", "b"}
    assert render_figure_crop(path, figure).startswith(b"\x89PNG")


def test_uncaptioned_figure_is_not_given_a_caption(tmp_path):
    path = tmp_path / "uncaptioned.pdf"
    _figure_pdf(path, caption=False)
    figures = detect_figure_candidates(path, "src-uncaptioned")
    assert len(figures) == 1
    assert figures[0].caption is None and figures[0].figure_number is None


def test_fake_provider_typed_result_cache_and_sidecar_round_trip(tmp_path):
    path = tmp_path / "figure.pdf"
    _figure_pdf(path)
    document = build_visual_document(path, "src-fig", include_figures=True)
    figure = document.figures[0]
    provider = FakeProvider()
    cache = FigureUnderstandingCache(tmp_path / "cache")
    image = render_figure_crop(path, figure)
    result = understand_with_cache(provider, cache, document.source_checksum, figure, image)
    cached = understand_with_cache(provider, cache, document.source_checksum, figure, image)
    interpreted = apply_understanding(figure, result, provider)
    assert provider.calls == 1 and cached.figure_type == "cycling_performance"
    assert interpreted.axes[1].unit == "mAh/g"
    assert interpreted.legend_entries[0].raw_label == "LFTO-700"
    assert interpreted.annotations[0].provenance.origin == "figure_annotation"
    assert interpreted.annotations[0].raw_text == "121.3 mAh/g"
    assert "curve" not in interpreted.model_dump_json().lower()
    updated = document.model_copy(update={"figures": [interpreted]})
    store = VisualSidecarStore(tmp_path / "sidecars")
    store.save(updated)
    loaded = store.require("src-fig")
    assert loaded.figures[0].figure_id == figure.figure_id
    assert store.list_objects("src-fig")[-1]["object_type"] == "figure"
    legacy_payload = document.model_dump()
    legacy_payload.pop("figures")
    assert VisualDocument.model_validate(legacy_payload).figures == []


def test_bounded_provider_output_rejects_invalid_figure_type():
    with pytest.raises(ValidationError):
        FigureUnderstandingResult.model_validate({"figure_type": "invented_chart_type"})
