import json
from pathlib import Path

from synthex_platform.core.identifiers import stable_id
from synthex_platform.extraction.battery_assembler import assemble_battery_archive
from synthex_platform.extraction.battery_evidence import verify_battery_evidence
from synthex_platform.extraction.battery_models import BatteryDocument
from synthex_platform.extraction.battery_table_conditions import enrich_table_condition_evidence
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext
from synthex_platform.visual.analytics.projection import project_archives
from synthex_platform.visual.analytics.specs import build_visualization_spec, surface_coverage
from synthex_platform.visual.models import TableCell, TableRecord, VisualProvenance


NMC_TABLE_FIXTURE = Path(__file__).parent / "fixtures" / "battery" / "energies_11_02275_tables.json"


def _nmc_source_bundle() -> SourceBundle:
    payload = json.loads(NMC_TABLE_FIXTURE.read_text(encoding="utf-8"))
    source = payload["source"]
    tables = []
    for item in payload["tables"]:
        grid = item["grid"]
        cells = []
        for row_index, row in enumerate(grid):
            for column_index, raw_text in enumerate(row):
                cell_id = f"{item['table_id']}:r{row_index}:c{column_index}"
                provenance = VisualProvenance(
                    source_id=source["source_id"],
                    page=item["page"],
                    object_id=item["table_id"],
                    table_number=item["table_number"],
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
        tables.append(TableRecord(
            table_id=item["table_id"],
            source_id=source["source_id"],
            page=item["page"],
            table_number=item["table_number"],
            caption=item["caption"],
            headers=[grid[0]],
            rows=grid[1:],
            cells=cells,
            parser="pymupdf_caption_text_fallback",
            extraction_confidence=1.0,
            raw_representation={"grid": grid},
            provenance=VisualProvenance(
                source_id=source["source_id"],
                page=item["page"],
                object_id=item["table_id"],
                table_number=item["table_number"],
            ),
        ))
    return SourceBundle(
        source=SourceMetadata(**source),
        pages=[
            SourcePageContext(
                page=item["page"],
                text=item["text"],
                native_text=item["text"],
                native_parser="pypdf",
                parser="pypdf",
            )
            for item in payload["pages"]
        ],
        tables=tables,
    )


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
    bundle = _nmc_source_bundle()
    doc = BatteryDocument.model_validate({
        "source": {
            "title": "Study on the Characteristics of a High Capacity Nickel Manganese Cobalt Oxide Battery",
            "doi": "10.3390/en11092275",
        },
        "paper_types": ["electrochemical_performance"],
        "battery_groups": [{
            "group_id": "group-nmc",
            "ownership": "focal_work",
            "battery_ids": ["NMC-cell"],
            "performance_points": [
                {
                    "property": "internal_resistance",
                    "raw_value": f"{value} mOhm",
                    "value": value,
                    "unit": "mOhm",
                    "qualifier": "exact",
                    "c_rate": "3 C",
                    "temperature": {
                        "raw_value": f"{temperature} °C",
                        "value": temperature,
                        "unit": "°C",
                        "qualifier": "exact",
                    },
                    "method": "3 C pulse discharge 10 s",
                    "ownership": "focal_work",
                    "evidence": [{
                        "page": 11,
                        "section": "3.2. Battery Internal Resistance",
                        "text_snippet": "Table 4. Battery ohmic resistance value under different battery internal temperature and SOC levels.",
                        "source_type": "table",
                    }],
                }
                for value, temperature in [(1.46, 25), (13.67, -30), (0.84, 55)]
            ],
        }],
    })

    enrich_table_condition_evidence(doc, bundle)
    matrix_points = [
        point for point in doc.battery_groups[0].performance_points
        if point.property == "internal_resistance"
    ]
    assert len(matrix_points) == 96
    assert all(isinstance(point.value, float) for point in matrix_points)
    assert all(point.ownership == "focal_work" for point in matrix_points)
    assert all(point.unit == "mOhm" for point in matrix_points)

    def condition(point, property_name):
        return next(item for item in point.additional_conditions if item.property == property_name)

    coordinates = {
        (condition(point, "state_of_charge").value, condition(point, "temperature").value)
        for point in matrix_points
    }
    assert len({coordinate[0] for coordinate in coordinates}) == 12
    assert len({coordinate[1] for coordinate in coordinates}) == 8
    assert len(coordinates) == 96
    assert all(condition(point, "state_of_charge").evidence for point in matrix_points)
    assert all(condition(point, "temperature").evidence for point in matrix_points)
    assert all(condition(point, "C_rate").value == 3.0 for point in matrix_points)
    assert all(
        evidence.table_id == "tbl-ff5bedb036551e50"
        and "cell_id=" in (evidence.locator or "")
        and evidence.original_source_type == "table_reported"
        for point in matrix_points
        for evidence in [next(item for item in point.evidence if item.locator)]
    )

    observed = {
        (condition(point, "state_of_charge").value, condition(point, "temperature").value): point.value
        for point in matrix_points
    }
    assert observed[(100.0, -30.0)] == 14.69
    assert observed[(100.0, 25.0)] == 1.56
    assert observed[(50.0, 25.0)] == 1.46
    assert observed[(5.0, 25.0)] == 3.17

    source_text = bundle.page_marked_text()
    verify_battery_evidence(doc, source_text)
    assert all(any(item.verbatim_match is True and item.locator for item in point.evidence) for point in matrix_points)
    archive = assemble_battery_archive(doc, source_text=source_text)
    rows = [row for row in project_archives([archive]) if row.property_name == "internal_resistance"]
    assert len(rows) == 96
    assert all(row.conditions["temperature_unit"] == "°C" for row in rows)
    assert all(row.conditions["state_of_charge_unit"] == "%" for row in rows)
    assert all(row.conditions["C_rate"] == 3.0 for row in rows)
    assert all(row.conditions["C_rate_unit"] == "C" for row in rows)
    assert all(
        row.source_id
        and row.visual_evidence_references
        and all(reference["source_id"] == row.source_id for reference in row.evidence_references)
        for row in rows
    )

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

    for chart_type in ("heatmap", "contour"):
        spec = build_visualization_spec(
            rows,
            chart_type,
            "NMC resistance surface",
            x_field="conditions.temperature",
            y_field="conditions.state_of_charge",
            z_field="value",
        )
        assert spec.eligible is True
        assert spec.reason is None


def test_table_2_duplicate_values_receive_exact_cell_evidence_without_weakening_admission():
    bundle = _nmc_source_bundle()
    points = []
    for property_name, value, unit, c_rate in [
        ("capacity", 73.3, "Ah", "1 C"),
        ("capacity", 74.1, "Ah", "0.5 C"),
        ("capacity", 78.9, "Ah", "0.33 C"),
        ("capacity", 81.2, "Ah", "0.05 C"),
        ("coulombic_efficiency", 102.8, "%", "1 C"),
        ("coulombic_efficiency", 102.8, "%", "0.5 C"),
        ("coulombic_efficiency", 101.6, "%", "0.33 C"),
        ("coulombic_efficiency", 105.8, "%", "0.05 C"),
    ]:
        points.append({
            "property": property_name,
            "raw_value": f"{value:g} {unit}",
            "value": value,
            "unit": unit,
            "qualifier": "exact",
            "c_rate": c_rate,
            "ownership": "focal_work",
            "evidence": [{
                "page": 9,
                "section": "3.1. Battery Capacity",
                "text_snippet": "Table 2. The battery discharge capacity under different discharge rate.",
                "source_type": "table",
                "table_id": "Table 2",
            }],
        })
    doc = BatteryDocument.model_validate({
        "source": {"title": "Table 2 fixture"},
        "paper_types": ["electrochemical_performance"],
        "battery_groups": [{
            "group_id": "group-nmc",
            "ownership": "focal_work",
            "performance_points": points,
        }],
    })

    enrich_table_condition_evidence(doc, bundle)
    table_points = doc.battery_groups[0].performance_points
    assert all(any(item.locator and "cell_id=" in item.locator for item in point.evidence) for point in table_points)

    source_text = bundle.page_marked_text()
    archive = assemble_battery_archive(doc, source_text=source_text)
    audit = archive.domain_payloads[0].values["admissibility"]
    admitted = [
        output
        for experiment in archive.experiments
        for output in experiment.outputs
        if output.property in {"capacity", "coulombic_efficiency"}
    ]
    assert len(admitted) == 8
    assert not any(item["reason"] == "no_verbatim_evidence" for item in audit["quarantine"])


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
