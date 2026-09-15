from __future__ import annotations

import csv
from io import StringIO
import json
from pathlib import Path
from zipfile import ZipFile
from io import BytesIO

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.models import (
    CalculationRecord,
    DomainPayload,
    Evidence,
    ExperimentRecord,
    MaterialEntity,
    Measurement,
    ProcessStep,
    Relationship,
    SourceRecord,
    SourceType,
)
from synthex_platform.export import export_csv_bundle, export_csv_bundle_zip, export_results_csv


def _rows(payload: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(payload.decode("utf-8-sig"))))


def _archive() -> SynthexArchive:
    evidence = Evidence(
        source_id="src-1",
        page=4,
        section="Results",
        source_type=SourceType.text,
        original_source_type="native_text",
        verbatim_match=True,
        text_snippet="MMONiCo reached approximately 80% CO₂ conversion at 350 °C.",
    )
    material = MaterialEntity(
        material_id="mat-1",
        name="MMONiCo",
        formula="Ni₀.₅Co₀.₅Oₓ",
        structure={"catalyst_state": "calcined"},
        tags=["catalyst", "ownership:focal_work"],
        evidence=[evidence],
    )
    process = ProcessStep(
        process_id="proc-1",
        name="Calcination",
        outputs=["mat-1"],
        parameters=[Measurement(
            property="temperature", raw_value="350 °C", value=350.0, unit="°C",
            qualifier="exact", evidence=[evidence],
        )],
        evidence=[evidence],
    )
    experiment = ExperimentRecord(
        experiment_id="exp-1",
        experiment_type="heterogeneous_catalysis",
        material_ids=["mat-1"],
        target="CO₂ methanation",
        conditions=[Measurement(
            property="temperature", raw_value="350 °C", value=350.0, unit="°C",
            qualifier="exact", evidence=[evidence],
        )],
        outputs=[Measurement(
            property="conversion", raw_value="~80%", value=80.0, unit="%", qualifier="approx",
            conditions={"reaction": "CO₂ methanation", "product": "CH₄", "temperature": "350 °C"},
            evidence=[evidence],
        )],
        evidence=[evidence],
    )
    calculation = CalculationRecord(
        calculation_id="calc-1",
        calculation_type="DFT",
        material_ids=["mat-1"],
        code="VASP",
        outputs=[Measurement(
            property="adsorption_energy", raw_value="-1.20 eV", value=-1.2, unit="eV",
            qualifier="exact", evidence=[evidence],
        )],
        evidence=[evidence],
    )
    relationship = Relationship(
        relation_id="rel-1", subject_id="mat-1", predicate="tested_in", object_id="exp-1",
        evidence=[evidence],
    )
    quarantine = {
        "path": "experiments.exp-cited.metrics.0",
        "reason": "ownership_cited_prior_work",
        "ownership": "cited_prior_work",
        "object": {
            "property": "conversion",
            "raw_value": "50%",
            "value": 50.0,
            "unit": "%",
            "qualifier": "exact",
            "product": "CH₄",
            "evidence": [{
                "source_id": "src-1", "page": 8, "source_type": "text",
                "original_source_type": "native_text", "verbatim_match": True,
                "text_snippet": "Earlier work reported 50% conversion.",
                "evidence_strength": "verified_native", "estimated": False,
            }],
        },
    }
    return SynthexArchive(
        metadata=ArchiveMetadata(archive_id="arc-1", domain="catalysis"),
        sources=[SourceRecord(
            source_id="src-1", title="Catalysis α-study", doi="10.1000/example", authors=["Ada", "Lin"],
        )],
        materials=[material],
        processes=[process],
        experiments=[experiment],
        calculations=[calculation],
        relationships=[relationship],
        domain_payloads=[DomainPayload(
            domain="catalysis", schema_version="1.0-stage2",
            values={"admissibility_audit": {"quarantine": [quarantine]}},
        )],
    )


def test_results_csv_is_canonical_by_default_and_preserves_scientific_text():
    rows = _rows(export_results_csv(_archive()))
    assert rows
    assert {row["admission_status"] for row in rows} == {"canonical"}
    result = next(row for row in rows if row["metric"] == "conversion")
    assert result["raw_value"] == "~80%"
    assert result["qualifier"] == "approx"
    assert result["reaction"] == "CO₂ methanation"
    assert result["temperature"] == "350 °C"
    assert result["material_formulas"] == "Ni₀.₅Co₀.₅Oₓ"
    assert result["ownership"] == "focal_work"
    assert result["evidence_origin"] == "native_text"
    assert result["evidence_strength"] == "verified_native"
    assert result["estimated"] == "False"
    assert result["source_page"] == "4"


def test_quarantine_is_only_in_explicit_all_results_export():
    default_rows = _rows(export_results_csv(_archive()))
    all_rows = _rows(export_results_csv(_archive(), include_quarantined=True))
    assert len(all_rows) == len(default_rows) + 1
    quarantined = next(row for row in all_rows if row["admission_status"] == "quarantined")
    assert quarantined["ownership"] == "cited_prior_work"
    assert quarantined["quarantine_reason"] == "ownership_cited_prior_work"
    assert quarantined["metric"] == "conversion"
    assert quarantined["source_page"] == "8"
    assert json.loads(quarantined["quarantined_object_json"])["value"] == 50.0
    bundle_evidence = _rows(export_csv_bundle(_archive(), include_quarantined=True).files["evidence.csv"])
    assert any(row["linked_record_id"] == quarantined["record_id"] for row in bundle_evidence)


def test_relational_bundle_has_stable_joinable_tables_and_dft_is_separate():
    bundle = export_csv_bundle(_archive())
    assert set(bundle.files) == {
        "sources.csv", "materials.csv", "processes.csv", "experiments.csv", "calculations.csv",
        "measurements.csv", "relationships.csv", "evidence.csv",
    }
    materials = _rows(bundle.files["materials.csv"])
    experiments = _rows(bundle.files["experiments.csv"])
    calculations = _rows(bundle.files["calculations.csv"])
    measurements = _rows(bundle.files["measurements.csv"])
    relationships = _rows(bundle.files["relationships.csv"])
    evidence = _rows(bundle.files["evidence.csv"])
    assert materials[0]["material_id"] == experiments[0]["material_ids"] == calculations[0]["material_ids"]
    assert calculations[0]["calculation_type"] == "DFT"
    assert all(row["experiment_type"] != "DFT" for row in experiments)
    dft_row = next(row for row in measurements if row["calculation_id"] == "calc-1")
    assert dft_row["record_type"] == "calculation"
    assert dft_row["value"] == "-1.2"
    assert dft_row["raw_value"] == "-1.20 eV"
    assert relationships[0]["subject_id"] == "mat-1"
    assert relationships[0]["object_id"] == "exp-1"
    assert evidence and all(row["source_id"] == "src-1" for row in evidence)
    assert materials[0]["evidence_ids"]


def test_formula_injection_is_escaped_but_negative_numbers_are_not():
    archive = _archive()
    archive.sources[0].title = '=HYPERLINK("https://example.invalid")'
    archive.experiments[0].outputs[0].evidence[0].text_snippet = "+cmd|' /C calc'!A0"
    rows = _rows(export_results_csv(archive))
    result = next(row for row in rows if row["metric"] == "conversion")
    dft = next(row for row in rows if row["metric"] == "adsorption_energy")
    assert result["source_title"].startswith("'=")
    assert result["evidence_snippet"].startswith("'+")
    assert dft["value"] == "-1.2"
    assert dft["raw_value"] == "-1.20 eV"


def test_ocr_and_digitized_evidence_remain_explicit_and_estimated_is_never_hidden():
    archive = _archive()
    output = archive.experiments[0].outputs[0]
    output.evidence[0].original_source_type = "ocr_extracted"
    output.evidence[0].verbatim_match = True
    row = next(row for row in _rows(export_results_csv(archive)) if row["metric"] == "conversion")
    assert row["evidence_origin"] == "ocr_extracted"
    assert row["evidence_strength"] == "verified_ocr"
    assert row["estimated"] == "False"

    output.evidence[0].original_source_type = "figure_digitized"
    output.evidence[0].verbatim_match = False
    row = next(row for row in _rows(export_results_csv(archive)) if row["metric"] == "conversion")
    assert row["evidence_origin"] == "figure_digitized"
    assert row["evidence_strength"] == "estimated_digitized"
    assert row["estimated"] == "True"


def test_nulls_are_blank_and_irregular_metadata_is_deterministic_json():
    bundle = export_csv_bundle(_archive())
    rows = _rows(bundle.files["calculations.csv"])
    assert rows[0]["functional"] == ""
    assert rows[0]["model_json"] == ""
    measurement = next(row for row in _rows(bundle.files["measurements.csv"]) if row["metric"] == "conversion")
    assert json.loads(measurement["conditions_json"])["product"] == "CH₄"


def test_empty_archive_returns_header_only_tables():
    archive = SynthexArchive(metadata=ArchiveMetadata(archive_id="arc-empty", domain="generic"))
    assert _rows(export_results_csv(archive)) == []
    bundle = export_csv_bundle(archive)
    assert all(_rows(payload) == [] for payload in bundle.files.values())


def test_quarantined_only_generic_archive_is_representable():
    archive = SynthexArchive(
        metadata=ArchiveMetadata(archive_id="arc-generic", domain="generic"),
        domain_payloads=[DomainPayload(domain="generic", schema_version="1", values={
            "admissibility": {"quarantined_objects": [{
                "kind": "experiment", "local_id": "example-1", "ownership": "example",
                "reason": "ownership_example", "raw_object": {"experiment_type": "example only"},
            }]},
        })],
    )
    assert _rows(export_results_csv(archive)) == []
    rows = _rows(export_results_csv(archive, include_quarantined=True))
    assert len(rows) == 1
    assert rows[0]["record_type"] == "experiment"
    assert rows[0]["admission_status"] == "quarantined"


def test_exports_are_deterministic_do_not_mutate_archive_and_make_no_external_calls(monkeypatch):
    archive = _archive()
    before = archive.model_dump_json()

    def forbidden(*args, **kwargs):  # pragma: no cover - only called on regression
        raise AssertionError("external call attempted")

    monkeypatch.setattr("socket.create_connection", forbidden)
    first = export_results_csv(archive, include_quarantined=True)
    second = export_results_csv(archive, include_quarantined=True)
    first_zip = export_csv_bundle_zip(archive, include_quarantined=True)
    second_zip = export_csv_bundle_zip(archive, include_quarantined=True)
    assert first == second
    assert first_zip == second_zip
    assert archive.model_dump_json() == before
    with ZipFile(BytesIO(first_zip)) as bundle:
        assert bundle.namelist() == sorted(bundle.namelist())
        assert bundle.read("measurements.csv").startswith(b"\xef\xbb\xbf")


def test_non_archive_input_is_rejected():
    try:
        export_results_csv({"metadata": {}})  # type: ignore[arg-type]
    except TypeError as exc:
        assert "validated SynthexArchive" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unvalidated input was accepted")


def test_primary_streamlit_app_exposes_existing_archive_downloads_without_extraction_call():
    source = Path("platform_app.py").read_text(encoding="utf-8")
    assert '"Download JSON"' in source
    assert '"Download CSV"' in source
    assert '"Download CSV Bundle"' in source
    assert 'st.session_state.get("synthex_last_archive")' in source
    assert "export_results_csv(archive)" in source
    assert "export_csv_bundle_zip(archive)" in source


def test_existing_battery_and_catalysis_archives_export_offline():
    paths = (
        Path("benchmark/outputs/batteries_11_00142_archive.json"),
        Path("benchmark/catalysis_v1/outputs/remediation/gold-only/cat-gold-a_result.json"),
    )
    domains = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        archive = SynthexArchive.model_validate(payload.get("archive", payload))
        domains.append(archive.metadata.domain)
        assert _rows(export_results_csv(archive))
        assert export_csv_bundle_zip(archive).startswith(b"PK")
    assert domains == ["batteries", "catalysis"]
