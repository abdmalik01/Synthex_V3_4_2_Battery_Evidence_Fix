from synthex_platform.core.identifiers import stable_id
from synthex_platform.extraction.battery_assembler import assemble_battery_archive
from synthex_platform.extraction.battery_evidence import verify_battery_evidence
from synthex_platform.extraction.battery_models import BatteryDocument
from synthex_platform.extraction.battery_table_conditions import enrich_table_condition_evidence
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata
from synthex_platform.visual.analytics.projection import project_archives
from synthex_platform.visual.analytics.specs import build_visualization_spec, surface_coverage
from synthex_platform.visual.models import TableCell, TableRecord, VisualProvenance


def _table_fixture() -> TableRecord:
    table_id = stable_id("tbl", "fixture", 1, 0)
    grid = [
        ["SOC / Temperature", "-30 °C", "25 °C"],
        ["100%", "14.69", "1.56"],
        ["50%", "13.67", "1.46"],
    ]
    cells = []
    for row_index, row in enumerate(grid):
        for column_index, raw_text in enumerate(row):
            cell_id = f"{table_id}:r{row_index}:c{column_index}"
            provenance = VisualProvenance(
                source_id="src-fixture",
                page=1,
                object_id=table_id,
                table_number="4",
                row=row_index,
                column=column_index,
                cell_id=cell_id,
                raw_text=raw_text,
            )
            cells.append(TableCell(
                row=row_index,
                column=column_index,
                cell_id=cell_id,
                raw_text=raw_text,
                text=raw_text,
                provenance=provenance,
            ))
    return TableRecord(
        table_id=table_id,
        source_id="src-fixture",
        page=1,
        table_number="4",
        caption="Table 4. Battery ohmic resistance under temperature and SOC.",
        headers=[["SOC / Temperature", "-30 °C", "25 °C"]],
        rows=grid[1:],
        cells=cells,
        parser="pymupdf",
        extraction_confidence=1.0,
        raw_representation={"grid": grid},
        provenance=VisualProvenance(
            source_id="src-fixture",
            page=1,
            object_id=table_id,
            table_number="4",
        ),
    )


def _document_fixture() -> BatteryDocument:
    # The evidence snippets deliberately mirror how table rows are represented in
    # the marked source text. Later cells include the row prefix rather than a
    # synthetic non-contiguous "row-header + cell" string.
    points = []
    for soc, temperature, value, snippet in [
        (100, -30, 14.69, "100% 14.69"),
        (100, 25, 1.56, "100% 14.69 1.56"),
        (50, -30, 13.67, "50% 13.67"),
        (50, 25, 1.46, "50% 13.67 1.46"),
    ]:
        points.append({
            "property": "internal_resistance",
            "raw_value": f"{value} mΩ",
            "value": value,
            "unit": "mOhm",
            "qualifier": "exact",
            "ownership": "focal_work",
            "additional_conditions": [
                {
                    "property": "state_of_charge",
                    "raw_value": f"{soc}%",
                    "value": soc,
                    "unit": "%",
                    "qualifier": "exact",
                    "evidence": [],
                },
                {
                    "property": "temperature",
                    "raw_value": f"{temperature} °C",
                    "value": temperature,
                    "unit": "°C",
                    "qualifier": "exact",
                    "evidence": [],
                },
            ],
            "evidence": [{
                "page": 1,
                "section": "Table 4",
                "text_snippet": snippet,
                "source_type": "table",
                "table_id": "Table 4",
            }],
        })
    return BatteryDocument.model_validate({
        "source": {"title": "NMC matrix fixture"},
        "paper_types": ["electrochemical_performance"],
        "battery_groups": [{
            "group_id": "group-nmc",
            "ownership": "focal_work",
            "battery_ids": ["NMC-cell"],
            "variant_label": "NMC cell",
            "performance_points": points,
        }],
    })


def test_structured_table_axes_receive_verified_evidence_and_enable_contour():
    table = _table_fixture()
    bundle = SourceBundle(
        source=SourceMetadata(
            source_id="src-fixture",
            filename="fixture.pdf",
            source_checksum="fixture-checksum",
        ),
        tables=[table],
    )
    doc = _document_fixture()

    enrich_table_condition_evidence(doc, bundle)

    for point in doc.battery_groups[0].performance_points:
        assert all(condition.evidence for condition in point.additional_conditions)
        assert all(condition.evidence[0].table_id == table.table_id for condition in point.additional_conditions)
        assert all("row=" in (condition.evidence[0].locator or "") for condition in point.additional_conditions)

    source_text = """--- PAGE 1 ---
Table 4. Battery ohmic resistance under temperature and SOC.
SOC / Temperature -30 °C 25 °C
100% 14.69 1.56
50% 13.67 1.46
"""
    verify_battery_evidence(doc, source_text)
    archive = assemble_battery_archive(doc, source_text=source_text)
    rows = [row for row in project_archives([archive]) if row.property_name == "internal_resistance"]

    assert len(rows) == 4
    assert {row.conditions["state_of_charge"] for row in rows} == {50.0, 100.0}
    assert {row.conditions["temperature"] for row in rows} == {-30.0, 25.0}

    coverage = surface_coverage(
        rows,
        "conditions.temperature",
        "conditions.state_of_charge",
        "value",
    )
    assert coverage["joint_xyz"] == 4
    assert coverage["unique_x"] == 2
    assert coverage["unique_y"] == 2
    assert coverage["unique_coordinates"] == 4

    spec = build_visualization_spec(
        rows,
        "contour",
        "NMC resistance surface",
        x_field="conditions.temperature",
        y_field="conditions.state_of_charge",
        z_field="value",
    )
    assert spec.eligible is True
    assert spec.reason is None


def test_ambiguous_or_unrelated_table_axes_are_not_promoted():
    table = _table_fixture()
    bundle = SourceBundle(
        source=SourceMetadata(
            source_id="src-fixture",
            filename="fixture.pdf",
            source_checksum="fixture-checksum",
        ),
        tables=[table],
    )
    doc = _document_fixture()
    point = doc.battery_groups[0].performance_points[0]
    point.additional_conditions[1].raw_value = "99 °C"
    point.additional_conditions[1].value = 99

    enrich_table_condition_evidence(doc, bundle)

    assert point.additional_conditions[0].evidence == []
    assert point.additional_conditions[1].evidence == []
