from pathlib import Path

from synthex_platform.benchmarks import all_benchmarks
from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftExperiment, DraftMaterial, DraftSource, ExtractedDocument
)
from synthex_platform.graph import archive_to_graph
from synthex_platform.interoperability import to_optimade_structures
from synthex_platform.query import Query, search
from synthex_platform.storage import JsonlArchiveStore


def make_archive(domain="batteries"):
    evidence = Evidence(page=3, text_snippet="The authors measured 150 mAh/g.", confidence=0.95)
    draft = ExtractedDocument(
        source=DraftSource(title="Example source", doi="10.0000/example", year=2026),
        materials=[DraftMaterial(local_id="material_1", name="Example cathode", formula="LiFePO4", elements=["Li","Fe","P","O"], ownership="focal_work", evidence=[evidence])],
        experiments=[DraftExperiment(
            local_id="experiment_1",
            experiment_type="galvanostatic cycling",
            material_refs=["material_1"],
            target="Li-ion storage",
            conditions=[Measurement(property="C_rate", raw_value="1 C", value=1.0, unit="C")],
            outputs=[Measurement(property="specific_capacity", raw_value="150 mAh/g", value=150.0, unit="mAh/g", evidence=[evidence])],
            ownership="focal_work", evidence=[evidence],
        )],
        domain_values={"chemistry":"LFP"},
    )
    return assemble_archive(draft, domain=domain, model="test-model")


def test_registry_has_priority_domains():
    registry = DomainRegistry()
    slugs = {d["slug"] for d in registry.list_domains()}
    expected = {"batteries","catalysis","corrosion","mechanical","additive_manufacturing","photovoltaics","thermoelectrics","membranes","semiconductors","biomaterials","gas_sensing"}
    assert expected <= slugs


def test_benchmark_catalog_is_substantial():
    rows = all_benchmarks(DomainRegistry())
    assert len(rows) >= 20
    assert any(r["domain"] == "batteries" for r in rows)


def test_archive_assembly_and_quality():
    archive = make_archive()
    assert archive.metadata.domain == "batteries"
    assert archive.materials[0].formula == "LiFePO4"
    assert archive.quality.provenance_coverage > 0
    assert archive.quality.validation_status == "schema_validated"


def test_store_query_graph_and_optimade(tmp_path: Path):
    archive = make_archive()
    store = JsonlArchiveStore(tmp_path / "archives.jsonl")
    store.append(archive)
    assert store.count() == 1
    result = search(store.iter_archives(), Query(domain="batteries", element="Fe", property="specific_capacity"))
    assert len(result) == 1
    nodes, edges = archive_to_graph(archive)
    assert any(n["type"] == "property" for n in nodes)
    assert any(e["predicate"] == "tested_in" for e in edges)
    opt = to_optimade_structures(archive)
    assert opt[0]["type"] == "structures"
    assert opt[0]["attributes"]["chemical_formula_descriptive"] == "LiFePO4"
