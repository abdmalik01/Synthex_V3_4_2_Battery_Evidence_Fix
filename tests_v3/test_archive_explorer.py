from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.models import (
    CalculationRecord,
    DomainPayload,
    Evidence,
    ExperimentRecord,
    MaterialEntity,
    Measurement,
    Relationship,
    SourceRecord,
    SourceType,
)
from synthex_platform.explorer import (
    ExplorerFilters,
    archive_summary,
    build_archive_explorer,
    filter_options,
    filter_results,
    researcher_status,
    result_highlights,
)
from synthex_platform.export import export_results_rows_csv


def _archive(*, domain: str = "catalysis", calculations_only: bool = False) -> SynthexArchive:
    evidence = Evidence(
        source_id="src-explorer",
        page=5,
        section="Results",
        source_type=SourceType.text,
        original_source_type="native_text",
        verbatim_match=True,
        text_snippet="MMONiCo reached approximately 80% CO2 conversion at 350 °C.",
    )
    material = MaterialEntity(
        material_id="mat-mmonico", name="MMONiCo", formula="NiCoOₓ", evidence=[evidence],
    )
    experiment = ExperimentRecord(
        experiment_id="exp-methanation",
        experiment_type="heterogeneous_catalysis" if domain == "catalysis" else domain,
        material_ids=[material.material_id],
        target="CO2 methanation",
        conditions=[Measurement(
            property="temperature", raw_value="350 °C", value=350.0, unit="°C",
            qualifier="exact", evidence=[evidence],
        )],
        outputs=[Measurement(
            property="CO2 conversion", raw_value="~80 %", value=80.0, unit="%", qualifier="approx",
            conditions={"product": "CH4"}, evidence=[evidence],
        )],
        evidence=[evidence],
    )
    calculation = CalculationRecord(
        calculation_id="calc-dft", calculation_type="DFT", material_ids=[material.material_id],
        code="VASP", method="plane-wave DFT", functional="PBE",
        outputs=[Measurement(
            property="adsorption_energy", raw_value="-1.2 eV", value=-1.2, unit="eV",
            qualifier="exact", evidence=[evidence],
        )],
        evidence=[evidence],
    )
    quarantine = {
        "path": "experiments.cited.metrics.0",
        "reason": "ownership_cited_prior_work",
        "ownership": "cited_prior_work",
        "object": {
            "property": "CO2 conversion", "raw_value": "50 %", "value": 50.0, "unit": "%",
            "conditions": {"product": "CH4", "temperature": "350 °C"},
            "evidence": [{
                "source_id": "src-explorer", "page": 8, "source_type": "text",
                "original_source_type": "native_text", "verbatim_match": True,
                "text_snippet": "Prior work reported 50 % CO2 conversion at 350 °C.",
            }],
        },
    }
    return SynthexArchive(
        metadata=ArchiveMetadata(archive_id=f"arc-{domain}", domain=domain),
        sources=[SourceRecord(
            source_id="src-explorer", title="Explorer source", doi="10.1000/explorer",
        )],
        materials=[material],
        experiments=[] if calculations_only else [experiment],
        calculations=[calculation] if calculations_only else [],
        relationships=[] if calculations_only else [Relationship(
            relation_id="rel-tested", subject_id=material.material_id,
            predicate="tested_in", object_id=experiment.experiment_id, evidence=[evidence],
        )],
        domain_payloads=[DomainPayload(
            domain=domain, schema_version="1", values={"admissibility_audit": {"quarantine": [quarantine]}},
        )],
    )


def test_result_projection_defaults_to_canonical_and_quarantine_is_explicit_opt_in():
    canonical = build_archive_explorer(_archive())
    inclusive = build_archive_explorer(_archive(), include_quarantined=True)
    assert canonical.results
    assert {row["admission_status"] for row in canonical.results} == {"canonical"}
    assert len(inclusive.results) == len(canonical.results) + 1
    quarantined = next(row for row in inclusive.results if row["admission_status"] == "quarantined")
    assert quarantined["ownership"] == "cited_prior_work"
    assert quarantined["quarantine_reason"] == "ownership_cited_prior_work"


def test_all_supported_filters_and_local_search_are_deterministic():
    rows = build_archive_explorer(_archive(), include_quarantined=True).results
    canonical_result = next(row for row in rows if row["metric"] == "CO2 conversion" and row["admission_status"] == "canonical")
    cases = (
        ExplorerFilters(domain=("catalysis",)),
        ExplorerFilters(source_title=("Explorer source",)),
        ExplorerFilters(material_names=("MMONiCo",)),
        ExplorerFilters(experiment_type=("heterogeneous_catalysis",)),
        ExplorerFilters(reaction=("CO2 methanation",)),
        ExplorerFilters(metric=("CO2 conversion",)),
        ExplorerFilters(product=("CH4",)),
        ExplorerFilters(admission_status=("canonical",)),
        ExplorerFilters(ownership=("focal_work",)),
        ExplorerFilters(evidence_origin=("native_text",)),
        ExplorerFilters(estimated=False),
        ExplorerFilters(search="approximately 80%"),
    )
    for filters in cases:
        filtered = filter_results(rows, filters)
        assert canonical_result["record_id"] in {row["record_id"] for row in filtered}
        assert filtered == filter_results(rows, filters)
    assert filter_results(rows, ExplorerFilters(search="not in loaded archive")) == ()


def test_filter_options_come_only_from_loaded_rows():
    rows = build_archive_explorer(_archive()).results
    options = filter_options(rows)
    assert options["domain"] == ("catalysis",)
    assert {"MMONiCo", "NiCoOₓ", "mat-mmonico"}.issubset(options["material_names"])
    assert "CO2 conversion" in options["metric"]
    assert "invented" not in {value for values in options.values() for value in values}


def test_calculations_are_distinct_and_source_tracking_is_preserved():
    explorer = build_archive_explorer(_archive(calculations_only=True))
    assert explorer.experiments == ()
    assert len(explorer.calculations) == 1
    row = explorer.calculations[0]
    assert row["calculation_type"] == "DFT"
    assert row["calculated_property"] == "adsorption_energy"
    assert row["software"] == "VASP"
    assert row["functional"] == "PBE"
    assert row["source_page"] == 5
    assert row["evidence_snippet"].startswith("MMONiCo reached")
    assert all(result["record_type"] == "calculation" for result in explorer.results)


def test_relationship_view_is_simple_and_uses_only_archive_relationships():
    explorer = build_archive_explorer(_archive())
    assert explorer.relationships == ({
        "source_id": "mat-mmonico",
        "relation": "tested_in",
        "target_id": "exp-methanation",
        "relation_id": "rel-tested",
        "evidence_ids": explorer.relationships[0]["evidence_ids"],
    },)


def test_empty_and_quarantined_only_archives_have_clean_views():
    empty = SynthexArchive(metadata=ArchiveMetadata(archive_id="arc-empty", domain="generic"))
    assert all(not getattr(build_archive_explorer(empty), field) for field in (
        "results", "materials", "processes", "experiments", "calculations", "evidence", "relationships",
    ))
    quarantined_only = SynthexArchive(
        metadata=ArchiveMetadata(archive_id="arc-quarantine", domain="generic"),
        domain_payloads=[DomainPayload(domain="generic", schema_version="1", values={
            "admissibility": {"quarantined_objects": [{
                "kind": "experiment", "local_id": "example", "ownership": "example",
                "reason": "ownership_example", "raw_object": {"experiment_type": "example"},
            }]},
        })],
    )
    assert build_archive_explorer(quarantined_only).results == ()
    inclusive = build_archive_explorer(quarantined_only, include_quarantined=True)
    assert len(inclusive.results) == 1
    assert inclusive.results[0]["admission_status"] == "quarantined"


def test_cross_domain_archives_project_without_domain_specific_assumptions():
    assert build_archive_explorer(_archive(domain="gas_sensing")).results
    assert build_archive_explorer(_archive(domain="batteries")).results
    assert build_archive_explorer(_archive(domain="generic")).results
    paths = (
        Path("benchmark/outputs/batteries_11_00142_archive.json"),
        Path("benchmark/catalysis_v1/outputs/remediation/gold-only/cat-gold-a_result.json"),
    )
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        archive = SynthexArchive.model_validate(payload.get("archive", payload))
        build_archive_explorer(archive)


def test_research_summary_highlights_and_trust_labels_are_archive_only():
    archive = _archive()
    explorer = build_archive_explorer(archive, include_quarantined=True)
    summary = archive_summary(archive)
    assert summary["title"] == "Explorer source"
    assert summary["materials"] == 1
    assert summary["experiments"] == 1
    assert summary["admitted_observations"] >= 1
    assert summary["quarantined_observations"] == 1
    highlights = result_highlights(explorer.results, limit=2)
    assert len(highlights) == 2
    assert all(item["researcher_status"] in {"Verified", "Admitted", "Estimated", "Needs review"} for item in highlights)
    quarantined = next(row for row in explorer.results if row["admission_status"] == "quarantined")
    assert researcher_status(quarantined) == "Needs review"


def test_result_highlights_limit_is_bounded():
    rows = build_archive_explorer(_archive()).results
    assert result_highlights(rows, limit=0) == ()
    with pytest.raises(ValueError, match="non-negative"):
        result_highlights(rows, limit=-1)


def test_projection_and_filtered_csv_do_not_mutate_or_call_external_services(monkeypatch):
    archive = _archive()
    before = archive.model_dump_json()

    def forbidden(*args, **kwargs):  # pragma: no cover - called only on a regression
        raise AssertionError("external call attempted")

    monkeypatch.setattr("socket.create_connection", forbidden)
    explorer = build_archive_explorer(archive, include_quarantined=True)
    csv_payload = export_results_rows_csv(filter_results(explorer.results, ExplorerFilters(metric=("CO2 conversion",))))
    assert csv_payload.startswith(b"\xef\xbb\xbf")
    assert archive.model_dump_json() == before


def test_archive_explorer_streamlit_smoke_uses_session_archive_without_extraction():
    at = AppTest.from_file(Path(__file__).parents[1] / "platform_app.py", default_timeout=25)
    at.session_state["synthex_last_archive"] = _archive().model_dump(mode="json", exclude_none=True)
    at.session_state["synthex_last_route"] = "catalysis"
    at.run()
    at.sidebar.radio[0].set_value("Explore Results").run()
    assert not at.exception
    assert any(item.value == "Explore Results" for item in at.subheader)
    assert [item.label for item in at.toggle] == ["Include quarantined"]
    assert len(at.tabs) == 7
    assert at.dataframe


def test_research_ui_home_has_primary_workflows_and_public_navigation():
    at = AppTest.from_file(Path(__file__).parents[1] / "platform_app.py", default_timeout=25).run()
    assert not at.exception
    assert any(item.value == "SYNTHEX" for item in at.title)
    assert {button.label for button in at.button} >= {"Analyze papers", "Discover papers"}
    options = set(at.sidebar.radio[0].options)
    assert {"Analyze Papers", "Explore Results", "Visualize Data", "Gas Sensing Analytics", "Figure Data"} <= options
    assert not any(option.startswith("Developer ·") for option in options)
