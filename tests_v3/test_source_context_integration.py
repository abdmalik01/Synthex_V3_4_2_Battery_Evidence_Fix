from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pymupdf

from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction.battery_assembler import assemble_battery_archive
from synthex_platform.extraction.battery_evidence import verify_battery_evidence
from synthex_platform.extraction.battery_extractor import BatteryGeminiExtractor
from synthex_platform.extraction.battery_models import (
    BatteryDerivation, BatteryDocument, BatteryEvidence, BatteryGroup,
    BatteryPerformancePoint, BatterySource,
)
from synthex_platform.extraction.domain_extractor import DomainGeminiExtractor
from synthex_platform.extraction.draft_models import ExtractedDocument, DraftSource
from synthex_platform.extraction.pipeline import SynthexExtractionPipeline
from synthex_platform.extraction.source_context import (
    SourceBundle, SourceMetadata, SourcePageContext, build_source_bundle,
    compact_source_context,
)
from synthex_platform.visual.digitization.models import (
    AxisCalibration, DigitizationResult, DigitizationUncertainty, PixelBoundingBox, PlotArea,
)
from synthex_platform.visual.models import (
    FigureAxis, FigureRecord, OCRPageResult, OCRQualityReport, TableCell,
    TableRecord, VisualProvenance,
)
from synthex_platform.visual.ocr.providers import OCRProvider
from synthex_platform.visual.sidecar_store import VisualSidecarStore


def _table_bundle() -> SourceBundle:
    table_id = "tbl-integration"
    table_provenance = VisualProvenance(
        origin="table_reported", source_id="src-integration", page=2,
        object_id=table_id, object_type="table", parser_or_method="pymupdf",
    )
    grid = [
        ["Anode biocatalyst", "Cathode biocatalyst", "Electrolyte", "Areal capacity"],
        ["glucose dehydrogenase", "bilirubin oxidase", "phosphate buffer", "0.5 mAh/cm²"],
    ]
    cells = []
    for row, values in enumerate(grid):
        for column, raw_text in enumerate(values):
            cell_id = f"{table_id}-r{row}-c{column}"
            cells.append(TableCell(
                row=row, column=column, cell_id=cell_id, raw_text=raw_text, text=raw_text,
                provenance=table_provenance.model_copy(update={
                    "row": row, "column": column, "cell_id": cell_id, "raw_text": raw_text,
                }),
            ))
    table = TableRecord(
        table_id=table_id, source_id="src-integration", page=2,
        caption="Table 1. Paper-based battery examples.", headers=[grid[0]], rows=[grid[1]],
        cells=cells, column_units={"Areal capacity": "mAh/cm²"},
        raw_representation={"grid": grid}, provenance=table_provenance,
    )
    figure = FigureRecord(
        figure_id="fig-integration", source_id="src-integration", page=3,
        caption="Fig. 2. Device output during operation.", figure_type="generic_plot",
        axes=[FigureAxis(role="x", raw_label="Time", unit="h")],
        provenance=VisualProvenance(
            origin="figure_caption", source_id="src-integration", page=3,
            object_id="fig-integration", object_type="figure",
        ),
    )
    ocr = OCRPageResult(
        source_id="src-integration", page=4, engine="fake", dpi=300,
        raw_text="OCR source reports about 1.2 V without scientific autocorrection.",
        normalized_text="OCR source reports about 1.2 V without scientific autocorrection.",
        quality=OCRQualityReport(status="succeeded"),
        provenance=VisualProvenance(
            origin="ocr_extracted", source_id="src-integration", page=4,
            object_id="ocr-page-4", object_type="ocr_block",
        ),
    )
    return SourceBundle(
        source=SourceMetadata(
            source_id="src-integration", filename="paper-battery-review.pdf",
            source_checksum="abc123", visual_sidecar_reference="sidecars/visual_document.json",
        ),
        pages=[
            SourcePageContext(
                page=1, native_text="Native introduction text.", text="Native introduction text.",
                native_parser="pypdf", parser="pypdf", sufficient=True,
                attempt_history=["pypdf"],
            ),
            SourcePageContext(
                page=4, native_text="", text=ocr.raw_text, native_parser="pymupdf",
                parser="ocr", origin="ocr_extracted", sufficient=True,
                attempt_history=["pypdf", "pymupdf", "ocr"],
            ),
        ],
        tables=[table], figures=[figure], ocr_blocks=[ocr],
    )


def _draw_native_table(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=600, height=400)
    page.insert_text((72, 55), "Table 1. Electrochemical performance and source context.")
    x0, y0, width, height = 72, 85, 460, 90
    columns, rows = 4, 2
    for column in range(columns + 1):
        x = x0 + column * width / columns
        page.draw_line((x, y0), (x, y0 + height))
    for row in range(rows + 1):
        y = y0 + row * height / rows
        page.draw_line((x0, y), (x0 + width, y))
    values = (
        ["Sample", "Temp (C)", "Capacity (mAh/g)", "Rct (ohm)"],
        ["Li2FeTiO4", "700 C", "121.3 mAh/g", "1258.6 ohm"],
    )
    for row, row_values in enumerate(values):
        for column, value in enumerate(row_values):
            page.insert_text((x0 + 4 + column * width / columns, y0 + 27 + row * height / rows), value, fontsize=7)
    document.save(path)
    document.close()


class _FakeOCRProvider(OCRProvider):
    provider_name = "fake_ocr"

    def __init__(self):
        self.calls: list[int] = []

    def recognize_page(self, pdf_path, page, source_id, language, dpi):
        self.calls.append(page)
        raw = "Li2FeTiO4 scanned scientific result at 700 C and 121.3 mAh/g."
        return OCRPageResult(
            source_id=source_id, page=page, engine="fake", language=language, dpi=dpi,
            raw_text=raw, normalized_text=raw, quality=OCRQualityReport(status="succeeded"),
            provenance=VisualProvenance(
                origin="ocr_extracted", source_id=source_id, page=page,
                object_id=f"ocr-page-{page}", object_type="ocr_block",
            ),
        )


def test_pdf_source_bundle_serializes_stable_tables_parser_history_and_sidecar(tmp_path):
    pdf = tmp_path / "native-table.pdf"
    _draw_native_table(pdf)
    store = VisualSidecarStore(tmp_path / "sidecars")
    first = build_source_bundle(pdf, enable_ocr=False, include_figures=False, sidecar_store=store)
    second = build_source_bundle(pdf, enable_ocr=False, include_figures=False, sidecar_store=store)
    restored = SourceBundle.model_validate_json(first.model_dump_json())

    assert first.source.source_id == second.source.source_id
    assert first.tables[0].table_id == second.tables[0].table_id
    assert restored.tables[0].cells[0].provenance.bbox is not None
    assert restored.pages[0].native_text and restored.pages[0].native_parser in {"pypdf", "pymupdf"}
    assert restored.pages[0].attempt_history
    assert restored.source.visual_sidecar_reference
    assert Path(restored.source.visual_sidecar_reference).exists()


def test_source_bundle_invokes_ocr_only_for_insufficient_page_and_preserves_origin(tmp_path):
    source = pymupdf.open()
    page = source.new_page()
    page.insert_text((72, 72), "image-only scientific page")
    pixmap = page.get_pixmap()
    source.close()
    pdf = tmp_path / "scan.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_image(page.rect, stream=pixmap.tobytes("png"))
    document.save(pdf)
    document.close()

    provider = _FakeOCRProvider()
    bundle = build_source_bundle(pdf, ocr_provider=provider, include_figures=False)
    assert provider.calls == [1]
    assert bundle.pages[0].origin == "ocr_extracted"
    assert bundle.pages[0].attempt_history == ["pypdf", "pymupdf", "ocr"]
    assert bundle.ocr_blocks[0].provenance.origin == "ocr_extracted"


def test_compact_context_has_table_cells_semantic_figure_ocr_and_no_digitized_points():
    bundle = _table_bundle()
    calibration = {
        "x": AxisCalibration(axis="x", pixel_start=0, pixel_end=100, data_start=0, data_end=10),
        "y": AxisCalibration(axis="y", pixel_start=100, pixel_end=0, data_start=0, data_end=5),
    }
    bundle.digitizations = [DigitizationResult(
        digitization_id="dig-integration", source_id=bundle.source.source_id, page=3,
        figure_id="fig-integration", plot_area=PlotArea(
            bbox=PixelBoundingBox(x0=0, y0=0, x1=100, y1=100),
            resolution_width=100, resolution_height=100,
        ),
        source_image_checksum="image-checksum", calibration=calibration,
        uncertainty=DigitizationUncertainty(x=0.1, y=0.1, pixel_x=1, pixel_y=1),
        status="completed", provenance={"origin": "figure_digitized"},
    )]
    payload = json.loads(compact_source_context(bundle, {
        "process_vocabulary": ["electrolyte", "biocatalyst"],
        "properties": ["areal_capacity"],
    }))

    assert payload["tables"][0]["cells"][7] == {
        "row": 1, "column": 3, "cell_id": "tbl-integration-r1-c3",
        "raw_text": "0.5 mAh/cm²", "bbox": None,
    }
    assert payload["figures"][0]["figure_id"] == "fig-integration"
    assert payload["ocr_pages"][0]["origin"] == "ocr_extracted"
    assert payload["ocr_pages"][0]["evidence_strength"] == "verified_ocr"
    assert payload["digitization_references"][0]["estimated"] is True
    assert payload["digitization_references"][0]["admission_status"] == "not_submitted"
    assert "points" not in payload["digitization_references"][0]


class _CapturingModels:
    def __init__(self, payload):
        self.payload = payload
        self.prompt = None

    def generate_content(self, **kwargs):
        self.prompt = kwargs["contents"]
        return SimpleNamespace(text=json.dumps(self.payload))


def test_generic_extractor_preserves_table_and_ocr_evidence_locators():
    bundle = _table_bundle()
    table_evidence = {
        "source_id": bundle.source.source_id, "page": 2, "source_type": "table",
        "original_source_type": "table_reported", "table_id": "tbl-integration",
        "locator": "row=1;column=3;cell_id=tbl-integration-r1-c3",
        "text_snippet": "0.5 mAh/cm²",
    }
    ocr_evidence = {
        "source_id": bundle.source.source_id, "page": 4, "source_type": "text",
        "original_source_type": "ocr_extracted", "text_snippet": "about 1.2 V",
    }
    response = {
        "source": {"title": "Source-context fixture"},
        "experiments": [{
            "local_id": "experiment_1", "experiment_type": "paper battery comparison",
            "ownership": "focal_work", "evidence": [table_evidence],
            "outputs": [
                {"property": "areal_capacity", "raw_value": "0.5 mAh/cm²", "value": 0.5,
                 "unit": "mAh/cm²", "qualifier": "exact", "evidence": [table_evidence]},
                {"property": "voltage", "raw_value": "about 1.2 V", "value": 1.2,
                 "unit": "V", "qualifier": "approx", "evidence": [ocr_evidence]},
            ],
        }],
    }
    extractor = DomainGeminiExtractor.__new__(DomainGeminiExtractor)
    extractor.registry = DomainRegistry()
    extractor.model = "offline-fake"
    models = _CapturingModels(response)
    extractor.client = SimpleNamespace(models=models)

    archive = extractor.extract_text(bundle.page_marked_text(), "generic", source_bundle=bundle)
    table_ev = archive.experiments[0].outputs[0].evidence[0]
    ocr_ev = archive.experiments[0].outputs[1].evidence[0]
    assert table_ev.table_id == "tbl-integration"
    assert table_ev.locator == "row=1;column=3;cell_id=tbl-integration-r1-c3"
    assert table_ev.original_source_type == "table_reported"
    assert ocr_ev.original_source_type == "ocr_extracted"
    assert "STRUCTURED SOURCE CONTEXT" in models.prompt


def test_review_values_gain_structure_but_remain_quarantined_and_derivation_is_explicit():
    snippets = {
        "approx": "The cited paper reported about 1.2 V.",
        "areal": "Its discharge capacity was 0.5 mAh/cm².",
        "loss": "The authors reported 6% loss after cycling.",
    }
    evidence = lambda key, row: [BatteryEvidence(
        page=2, source_type="table", original_source_type="table_reported",
        table_id="tbl-review", locator=f"row={row};column=2;cell_id=tbl-review-r{row}-c2",
        text_snippet=snippets[key],
    )]
    doc = BatteryDocument(
        source=BatterySource(title="Paper-based batteries: A review", pdf_text_parser="pymupdf"),
        paper_types=["electrochemical_performance"],
        battery_groups=[BatteryGroup(
            group_id="review-table", ownership="cited_prior_work",
            performance_points=[
                BatteryPerformancePoint(property="voltage", raw_value="about 1.2 V", value=1.2, unit="V", ownership="cited_prior_work", evidence=evidence("approx", 1)),
                BatteryPerformancePoint(property="areal capacity", raw_value="0.5 mAh/cm²", value=0.5, unit="mAh/cm²", qualifier="exact", ownership="cited_prior_work", evidence=evidence("areal", 2)),
                BatteryPerformancePoint(property="capacity loss", raw_value="6% loss", value=6, unit="%", qualifier="exact", ownership="cited_prior_work", evidence=evidence("loss", 3)),
                BatteryPerformancePoint(
                    property="capacity retention", raw_value="derived from 6% loss", value=94, unit="%",
                    qualifier="exact", ownership="cited_prior_work", evidence=evidence("loss", 3),
                    derivation=BatteryDerivation(
                        reported_property="capacity_loss", reported_raw_value="6% loss",
                        reported_value=6, transformation="100 - loss",
                    ),
                ),
            ],
        )],
    )
    source_text = "--- PAGE 2 ---\n" + " ".join(snippets.values())
    verify_battery_evidence(doc, source_text)
    archive = assemble_battery_archive(doc, source_text=source_text)
    raw_points = archive.domain_payloads[0].values["battery_groups"][0]["performance_points"]
    quarantine = archive.domain_payloads[0].values["admissibility"]["quarantine"]

    assert archive.experiments == []
    assert archive.domain_payloads[0].values["admissibility"]["admitted_quantitative_values"] == 0
    assert raw_points[0]["qualifier"] == "approx"
    assert raw_points[1]["property"] == "areal_capacity"
    assert raw_points[1]["unit"] == "mAh/cm²"
    assert raw_points[3]["derivation"]["transformation"] == "100 - loss"
    assert any(item["reason"] == "derived_value_not_reported" for item in quarantine)
    assert all(item["evidence"][0]["table_id"] == "tbl-review" for item in quarantine)


def test_battery_prompt_keeps_enzyme_columns_distinct_and_text_only_api_stays_compact():
    extractor = BatteryGeminiExtractor.__new__(BatteryGeminiExtractor)
    structured = extractor.build_prompt("flattened text", source_bundle=_table_bundle())
    text_only = extractor.build_prompt("plain supplied text")
    native_only = _table_bundle().model_copy(update={
        "tables": [], "figures": [], "ocr_blocks": [], "digitizations": [],
        "pages": [SourcePageContext(
            page=1, native_text="native", text="native", native_parser="pypdf",
            parser="pypdf", sufficient=True, attempt_history=["pypdf"],
        )],
    })
    native_only_prompt = extractor.build_prompt("native", source_bundle=native_only)
    assert "Anode biocatalyst" in structured and "glucose dehydrogenase" in structured
    assert "Cathode biocatalyst" in structured and "bilirubin oxidase" in structured
    assert "phosphate buffer" in structured
    assert "do not classify" in structured
    assert "STRUCTURED SOURCE CONTEXT (bounded, loss-aware JSON):" not in text_only
    assert "STRUCTURED SOURCE CONTEXT (bounded, loss-aware JSON):" not in native_only_prompt


def test_pipeline_forwards_bundle_records_parser_metadata_and_keeps_text_api(monkeypatch):
    from synthex_platform.extraction import pipeline as pipeline_module
    from synthex_platform.extraction.assembler import assemble_archive

    received = []

    class FakeDomainExtractor:
        model = "offline-fake"

        def __init__(self, **kwargs):
            pass

        def extract_text(self, text, domain, source_bundle=None):
            received.append(source_bundle)
            return assemble_archive(
                ExtractedDocument(source=DraftSource(title="Offline pipeline fixture")),
                domain=domain, model=self.model,
            )

    monkeypatch.setattr(pipeline_module, "DomainGeminiExtractor", FakeDomainExtractor)
    pipeline = SynthexExtractionPipeline(search_assisted=False)
    bundle = _table_bundle()
    route, archive = pipeline.extract_source_bundle(bundle, domain="generic")
    source_context = archive.domain_payloads[0].values["source_context"]
    assert route.domain == "generic" and received[-1] is bundle
    assert archive.sources[0].checksum == "abc123"
    assert source_context["page_parsers"][1]["origin"] == "ocr_extracted"
    assert source_context["page_parsers"][1]["attempt_history"][-1] == "ocr"
    assert source_context["visual_sidecar_reference"] == "sidecars/visual_document.json"

    pipeline.extract_text("already supplied text", domain="generic")
    assert received[-1] is None

    class FakeBatteryExtractor:
        model = "offline-fake"

        def __init__(self, **kwargs):
            pass

        def extract_text(self, text, source_bundle=None):
            assert source_bundle is bundle
            return BatteryDocument(source=BatterySource(title="Battery parser fixture"))

    monkeypatch.setattr(pipeline_module, "BatteryGeminiExtractor", FakeBatteryExtractor)
    _, battery_archive = pipeline.extract_source_bundle(bundle, domain="batteries")
    battery_values = battery_archive.domain_payloads[0].values
    assert battery_values["pdf_text_parser"] == "pypdf"
    assert battery_values["source_context"]["primary_native_parser"] == "pypdf"
