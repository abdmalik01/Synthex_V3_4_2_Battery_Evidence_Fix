from synthex_platform.core.identifiers import stable_id
from synthex_platform.extraction.battery_assembler import assemble_battery_archive
from synthex_platform.extraction.battery_evidence import verify_battery_evidence
from synthex_platform.extraction.battery_models import BatteryDocument
from synthex_platform.extraction.battery_table_conditions import enrich_table_condition_evidence
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext
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


def test_dense_soc_temperature_matrix_recovers_all_96_observations():
    page_text = """Table 4. Battery ohmic resistance value under different battery internal temperature and SOC levels.
SOC −30 °C −20 °C −10 °C 0 °C 10 °C 25 °C 45 °C 55 °C
100% 14.69 10.07 6.51 4.01 2.65 1.56 1.06 0.92
95% 14.36 9.75 6.31 3.83 2.59 1.56 1.07 0.93
90% 14.10 9.50 6.17 3.74 2.57 1.57 1.09 0.95
80% 13.77 9.20 6.01 3.67 2.54 1.60 1.15 1.00
70% 13.58 9.10 5.94 3.67 2.57 1.64 1.18 1.04
60% 13.58 9.10 5.90 3.72 2.61 1.66 1.16 1.02
50% 13.67 9.22 5.81 3.66 2.47 1.46 0.97 0.84
40% 13.94 9.46 5.88 3.64 2.39 1.45 0.98 0.87
30% 14.51 9.95 6.16 3.82 2.49 1.53 1.00 0.88
20% 15.66 10.90 6.69 4.16 2.76 1.67 1.06 0.92
10% 18.32 13.68 8.28 5.16 3.57 2.14 1.16 0.96
5% 29.98 27.81 10.91 6.77 5.06 3.17 1.43 1.15
"""
    bundle = SourceBundle(
        source=SourceMetadata(
            source_id="src-nmc",
            filename="energies-11-02275.pdf",
            source_checksum="fixture-checksum",
        ),
        pages=[SourcePageContext(page=11, text=page_text, native_text=page_text)],
    )
    doc = BatteryDocument.model_validate({
        "source": {"title": "NMC matrix fixture"},
        "paper_types": ["electrochemical_performance"],
        "battery_groups": [{
            "group_id": "group-nmc",
            "ownership": "focal_work",
            "battery_ids": ["NMC-cell"],
            "performance_points": [{
                "property": "internal_resistance",
                "raw_value": "14.69 mΩ",
                "value": 14.69,
                "unit": "mΩ",
                "qualifier": "exact",
                "temperature": {"raw_value": "-30 °C", "value": -30, "unit": "°C", "qualifier": "exact"},
                "additional_conditions": [{
                    "property": "state_of_charge",
                    "raw_value": "100%",
                    "value": 100,
                    "unit": "%",
                    "qualifier": "exact",
                    "evidence": [],
                }],
                "ownership": "focal_work",
                "evidence": [{
                    "page": 11,
                    "section": "Table 4",
                    "text_snippet": "100% | 14.69",
                    "source_type": "table",
                    "table_id": "Table 4",
                }],
            }],
        }],
    })

    enrich_table_condition_evidence(doc, bundle)
    matrix_points = [
        point for point in doc.battery_groups[0].performance_points
        if point.property == "internal_resistance"
    ]
    assert len(matrix_points) == 96

    source_text = f"--- PAGE 11 ---\n{page_text}"
    verify_battery_evidence(doc, source_text)
    archive = assemble_battery_archive(doc, source_text=source_text)
    rows = [row for row in project_archives([archive]) if row.property_name == "internal_resistance"]
    assert len(rows) == 96

    coverage = surface_coverage(
        rows,
        "conditions.temperature",
        "conditions.state_of_charge",
        "value",
    )
    assert coverage["joint_xyz"] == 96
    assert coverage["unique_x"] == 8
    assert coverage["unique_y"] == 12
    assert coverage["unique_coordinates"] == 96

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
