from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest
import yaml

from benchmark.membranes_v1.interim_audit import run_interim_audit
from benchmark.membranes_v1.recover_cases import recover_all_cases
from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.export.analytics_projection import project_results_rows
from synthex_platform.extraction.draft_models import DraftDevice, DraftDeviceLayer
from synthex_platform.extraction.membranes_contract import (
    membranes_admission_decision,
    membranes_device_decision,
)
from synthex_platform.extraction.router import DomainRouter


ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "benchmark" / "membranes_v1"


@pytest.fixture(scope="module")
def cases():
    return recover_all_cases()


def _table_measurement(property_name: str, value: float, unit: str, **conditions) -> Measurement:
    raw = f"{value:g}"
    return Measurement(
        property=property_name, raw_value=raw, value=value, unit=unit, qualifier="exact",
        conditions=conditions,
        evidence=[Evidence(
            page=1, source_type=SourceType.table, original_source_type="publisher_pdf_table",
            verbatim_match=True, text_snippet=f"row value {raw}", table_id="Table 1", locator="row=1",
        )],
    )


def test_membranes_manifest_has_disjoint_modalities_and_unit_families():
    manifest = yaml.safe_load((ROOT / "synthex_platform" / "domains" / "manifests" / "membranes.yaml").read_text(encoding="utf-8"))
    properties = {item["key"]: item for item in manifest["properties"]}
    assert manifest["version"] == "1.2.0"
    assert {"gas_permeability", "gas_permeance", "ideal_selectivity", "mixed_gas_selectivity"} <= properties.keys()
    assert "Barrer" in properties["gas_permeability"]["units"]
    assert "GPU" in properties["gas_permeance"]["units"]
    assert "GPU" not in properties["gas_permeability"]["units"]
    assert properties["membrane_thickness"]["key"] != properties["selective_layer_thickness"]["key"]


def test_membrane_contract_rejects_barrer_gpu_confusion_caption_only_and_na():
    base = {
        "scientific_type": "reported_measurement", "species": "CO2", "test_mode": "pure_gas",
        "temperature": 25.0, "temperature_unit": "C", "pressure_kind": "feed_pressure",
    }
    valid = _table_measurement("gas_permeability", 10.0, "Barrer", **base)
    assert membranes_admission_decision(valid, role="result", modality="gas_separation").admitted
    wrong = _table_measurement("gas_permeability", 10.0, "GPU", **base)
    assert not membranes_admission_decision(wrong, role="result", modality="gas_separation").admitted

    caption = valid.model_copy(deep=True)
    caption.evidence[0].source_type = SourceType.figure_caption
    caption.evidence[0].original_source_type = "figure_caption"
    assert not membranes_admission_decision(caption, role="result", modality="gas_separation").admitted

    missing = valid.model_copy(update={"raw_value": "N/A", "value": 0.0})
    missing.evidence[0].text_snippet = "row value N/A"
    assert not membranes_admission_decision(missing, role="result", modality="gas_separation").admitted


def test_ideal_and_mixed_gas_selectivity_require_their_own_test_basis():
    ideal = _table_measurement(
        "ideal_selectivity", 40.0, "dimensionless", scientific_type="reported_derived_metric",
        species_pair="CO2/N2", test_mode="pure_gas", temperature=30.0, temperature_unit="C",
    )
    assert membranes_admission_decision(ideal, role="result", modality="gas_separation").admitted
    assert not membranes_admission_decision(
        ideal.model_copy(update={"conditions": {**ideal.conditions, "test_mode": "mixed_gas"}}),
        role="result", modality="gas_separation",
    ).admitted


def test_membrane_device_contract_preserves_ordered_multilayer_roles():
    layers = [
        DraftDeviceLayer(sequence_index=0, role="substrate", material_ref="pps"),
        DraftDeviceLayer(sequence_index=1, role="porous_support", material_ref="pbi"),
        DraftDeviceLayer(sequence_index=2, role="selective_layer", material_ref="polyimide"),
        DraftDeviceLayer(sequence_index=3, role="protective_layer", material_ref="teflon"),
    ]
    device = DraftDevice(
        local_id="d1", device_type="membrane_specimen", layer_stack=layers,
        configuration={"membrane_modality": "gas_separation", "architecture_type": "multilayer_composite"},
    )
    assert membranes_device_decision(device).admitted
    swapped = device.model_copy(update={"layer_stack": [layers[0], layers[2], layers[1], layers[3]]})
    swapped.layer_stack[1].sequence_index = 2
    swapped.layer_stack[2].sequence_index = 1
    assert membranes_device_decision(swapped).admitted
    missing_support = device.model_copy(update={"layer_stack": [
        DraftDeviceLayer(sequence_index=0, role="selective_layer", material_ref="polyimide")
    ]})
    assert not membranes_device_decision(missing_support).admitted


def test_four_foundation_sources_route_to_membranes():
    router = DomainRouter()
    foundation = (
        "MEM-GOLD-A_article.pdf", "MEM-SEP-B_article.pdf",
        "MEM-STAB-C_article.pdf", "MEM-PROCESS-D_article.pdf",
    )
    for name in foundation:
        pdf_path = CASE_DIR / "corpus_pdfs" / name
        with pymupdf.open(pdf_path) as document:
            text = "\n".join(page.get_text() for page in document)
        route = router.route_text(text)
        assert route.domain == "membranes", pdf_path.name
        assert any(signal.startswith("membrane_") for signal in route.focal_signals["membranes"])


@pytest.mark.parametrize("text,expected", [
    (
        "A lithium-ion battery separator was evaluated by charge-discharge cycling, specific capacity, "
        "coulombic efficiency, electrolyte uptake, and electrochemical impedance spectroscopy.",
        "batteries",
    ),
    ("The porous layer showed permeability, selectivity, flux, diffusion and transport changes.", "generic"),
    ("The biological cell membrane controls ion transport and protein diffusion in biomaterial scaffolds.", "generic"),
])
def test_weak_or_cross_domain_terms_do_not_route_to_membranes(text: str, expected: str):
    assert DomainRouter().route_text(text).domain == expected


def test_locked_sources_and_frozen_gold_recover_expected_counts(cases):
    counts = {case_id: sum(len(item.outputs) for item in archive.experiments) for case_id, archive in cases.items()}
    assert counts == {"MEM-GOLD-A": 12, "MEM-SEP-B": 98, "MEM-STAB-C": 25, "MEM-PROCESS-D": 30}
    for name in ("source_lock.json", "source_lock_sep_b.json", "source_lock_stab_c.json", "source_lock_process_d.json"):
        lock = json.loads((CASE_DIR / name).read_text(encoding="utf-8"))
        assert lock["status"] == "locked_before_provider_call"


def test_gold_a_preserves_mixed_gas_conditions_and_variant_association(cases):
    archive = cases["MEM-GOLD-A"]
    assert len(archive.devices) == 4
    for experiment in archive.experiments:
        assert experiment.device_id and experiment.device_ids == [experiment.device_id]
        for output in experiment.outputs:
            assert output.conditions["test_mode"] == "mixed_gas"
            assert output.conditions["transmembrane_pressure"] == 3.0
            assert output.conditions["temperature"] == 25.0
    assert {item.value for item in archive.experiments[2].outputs if item.property == "gas_permeability"} == {15.1, 0.34}


def test_sep_b_preserves_six_species_eight_pairs_and_whole_membrane_thickness(cases):
    archive = cases["MEM-SEP-B"]
    species = {output.conditions.get("species") for experiment in archive.experiments for output in experiment.outputs if output.property == "gas_permeability"}
    pairs = {output.conditions.get("species_pair") for experiment in archive.experiments for output in experiment.outputs if output.property == "ideal_selectivity"}
    assert species == {"O2", "N2", "CO2", "H2", "CH4", "C2H4"}
    assert len(pairs) == 8 and {"CO2/CH4", "H2/C2H4"} <= pairs
    assert all(
        layer["thickness"]["property"] == "membrane_thickness"
        and layer["thickness"]["conditions"]["thickness_scope"] == "whole_membrane"
        for device in archive.devices for layer in device.configuration["layer_stack"]
    )


def test_stab_c_keeps_initial_fouled_recovered_and_author_reported_frr_distinct(cases):
    archive = cases["MEM-STAB-C"]
    expected = ["initial_flux", "fouled_flux", "recovered_flux", "flux_recovery_ratio", "relative_flux_reduction"]
    assert all([output.property for output in experiment.outputs] == expected for experiment in archive.experiments)
    pz1 = archive.experiments[0].outputs
    assert [output.value for output in pz1] == [3.51, 3.37, 3.44, 97.93, 3.94]
    assert pz1[3].conditions["scientific_type"] == "reported_derived_metric"
    assert pz1[3].conditions["cleaning_method"] == "deionized-water wash for 15 min"


def test_process_d_retains_four_ordered_roles_and_species_specific_table_rows(cases):
    archive = cases["MEM-PROCESS-D"]
    for device in archive.devices:
        assert [layer["role"] for layer in device.configuration["layer_stack"]] == [
            "substrate", "porous_support", "selective_layer", "protective_layer"
        ]
    assert all(len(experiment.outputs) == 15 for experiment in archive.experiments)
    assert {output.property for output in archive.experiments[0].outputs} == {
        "gas_permeance", "activation_energy_of_permeance", "estimated_selective_layer_thickness"
    }
    co2_activation = [
        output for output in archive.experiments[1].outputs
        if output.property == "activation_energy_of_permeance" and output.conditions["species"] == "CO2"
    ][0]
    assert co2_activation.value == -3.45


def test_membrane_analytics_are_complete_and_uncontaminated(cases):
    rows = [
        row for archive in cases.values() for row in project_results_rows(archive)
        if row["measurement_role"] == "result" and row["admission_status"] == "canonical"
    ]
    assert len(rows) == 165
    assert all(row["domain"] == "membranes" and row["ownership"] == "focal_work" for row in rows)
    assert all(json.loads(row["conditions_json"])["membrane_variant"] for row in rows)


def test_interim_membrane_audit_passes_all_thirty_invariants():
    report = run_interim_audit()
    assert report["passed"] is True
    assert report["passed_invariants"] == 30
    assert report["contamination"] == {
        "ownership": 0, "evidence": 0, "cross_record_leakage": 0, "analytics": 0,
    }
    assert report["routing_safe"] is True
