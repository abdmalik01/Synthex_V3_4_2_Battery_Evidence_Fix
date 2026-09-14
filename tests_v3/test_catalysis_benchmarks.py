from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path

from pypdf import PdfReader

from benchmark_catalysis_corpus import REQUIRED_BENCHMARK_ROLES, identify_missing_categories, validate_manifest
from benchmark_catalysis_gold import (
    canonical_admission_counts,
    canonical_precision,
    contextual_value_match,
    detect_dft_leakage,
    detect_potential_conversion_violation,
    match_catalyst_identity,
    match_product_specific_metric,
    match_stability_association,
    referential_integrity_violations,
    review_contamination_count,
    validate_gold_record,
)
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.pipeline import _most_conservative_scope


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = REPO_ROOT / "benchmark" / "catalysis_v1"
CORPUS = BENCHMARK_ROOT / "corpus_pdfs"
MANIFEST_PATH = BENCHMARK_ROOT / "corpus_manifest.json"
GOLD_A_PATH = BENCHMARK_ROOT / "gold" / "gold_a_heterogeneous_experimental.json"
GOLD_B_PATH = BENCHMARK_ROOT / "gold" / "gold_b_electrocatalysis.json"


def _payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _long_path(path: Path) -> str:
    resolved = str(path.resolve())
    return "\\\\?\\" + resolved if os.name == "nt" else resolved


@lru_cache(maxsize=8)
def _pdf_text(filename: str) -> str:
    reader = PdfReader(_long_path(CORPUS / filename))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_real_manifest_has_exactly_seven_verified_roles_and_checksums():
    manifest = _payload(MANIFEST_PATH)
    result = validate_manifest(manifest, CORPUS)
    assert result == {"valid": True, "entry_count": 7, "missing_roles": [], "errors": []}
    assert set(entry["benchmark_role"] for entry in manifest["entries"]) == set(REQUIRED_BENCHMARK_ROLES)
    assert identify_missing_categories(manifest) == []


def test_real_manifest_routes_scope_and_subtypes_match_actual_pdfs():
    manifest = _payload(MANIFEST_PATH)
    router = DomainRouter()
    for entry in manifest["entries"]:
        route = router.route_text(_pdf_text(entry["filename"]))
        assert route.domain == entry["expected_route"], entry["benchmark_id"]
        assert route.scope_status == entry["expected_scope_status"], entry["benchmark_id"]
        assert set(entry["expected_subtypes"]).issubset(route.paper_types), entry["benchmark_id"]


def test_router_scope_cannot_be_upgraded_by_model_output():
    assert _most_conservative_scope("deferred_subtype", "supported") == "deferred_subtype"
    assert _most_conservative_scope("supported", "deferred_subtype") == "deferred_subtype"
    assert _most_conservative_scope("out_of_scope", "supported") == "out_of_scope"
    assert _most_conservative_scope("supported", "supported") == "supported"


def test_review_ner_abbreviation_does_not_trigger_materials_informatics_fallback():
    route = DomainRouter().route_text(
        "Heterogeneous catalyst conversion, reactor conditions, selectivity, yield, and time on stream are surveyed. "
        "This is a review. "
        "A bibliometric database and dataset report net energy ratio (NER)."
    )
    assert route.domain == "catalysis"
    assert route.ambiguity_reason != "materials_informatics_signals"


def test_gold_records_are_real_source_grounded_and_templates_are_non_scorable():
    manifest = _payload(MANIFEST_PATH)
    for path in (GOLD_A_PATH, GOLD_B_PATH):
        record = _payload(path)
        assert validate_gold_record(record)["valid"] is True
        assert record["curation"]["source_grounded"] is True
        assert record["curation"]["model_output_used"] is False
        manifest_entry = next(item for item in manifest["entries"] if item["benchmark_id"] == record["benchmark_id"])
        assert record["source"]["checksum"] == manifest_entry["checksum"]
    for template in (BENCHMARK_ROOT / "fixtures" / "templates").glob("*.json"):
        payload = _payload(template)
        assert payload["synthetic"] is True and payload["scorable"] is False
        assert validate_gold_record(payload)["valid"] is False


def test_contextual_value_match_rejects_wrong_or_missing_associations():
    expected = {
        "property": "productivity",
        "value": 168,
        "unit": "mol CH4 h-1 L-1",
        "product": "CH4",
        "context": {
            "catalyst": "MMONiCo + Ce",
            "catalyst_state": "activated",
            "reaction": "CO2 methanation",
            "temperature": "350 °C",
            "space_velocity": "36000 h-1",
        },
    }
    observed = {**expected, "context": dict(expected["context"])}
    assert contextual_value_match(expected, observed)
    observed["context"]["catalyst"] = "MMONiCo"
    assert not contextual_value_match(expected, observed)
    observed["context"] = {"catalyst": "MMONiCo + Ce"}
    assert not contextual_value_match(expected, observed)


def test_contextual_value_match_accepts_equivalent_pdf_degree_glyphs():
    expected = {
        "property": "productivity",
        "value": 168,
        "unit": "mol CH4 h-1 L-1",
        "context": {"catalyst": "MMONiCo + Ce", "temperature": "350 °C"},
    }
    observed = {
        "property": "productivity",
        "value": 168.0,
        "unit": "mol CH4 h-1 L-1",
        "context": {"catalyst": "MMONiCo + Ce", "temperature": "350 ◦C"},
    }
    assert contextual_value_match(expected, observed)


def test_metric_unit_scoring_accepts_equivalent_area_notation():
    assert contextual_value_match(
        {"property": "partial_current_density", "value": 0.5, "unit": "mA cm-2"},
        {"property": "partial_current_density", "value": 0.5, "unit": "mA/cm2"},
    )


def test_catalyst_identity_matching_requires_variant_state_and_components():
    expected = {
        "reported_name": "MMONiCo + Ce",
        "formula": "Mg4.7NiCo0.3Al2O9 + 0.3CeO2",
        "state": "activated",
        "variant_of": "cat_mmonico",
        "components": [
            {"role": "active_component", "reported_name": "Ni"},
            {"role": "promoter", "reported_name": "Co"},
            {"role": "support", "reported_name": "CeO2"},
        ],
    }
    assert match_catalyst_identity(expected, {**expected, "components": list(expected["components"])})
    assert not match_catalyst_identity(expected, {**expected, "components": expected["components"][:2]})
    assert not match_catalyst_identity(expected, {**expected, "state": "as_synthesized"})
    assert match_catalyst_identity(
        {"reported_name": "commercial polycrystalline Cu powder"},
        {"reported_name": "polycrystalline Cu powder"},
    )


def test_product_potential_reference_and_normalization_must_all_match():
    expected = {
        "property": "partial_current_density",
        "value": 0.5,
        "unit": "mA cm-2",
        "product": "n-propanol",
        "potential": "-0.75 V RHE",
        "reference_electrode": "RHE",
        "normalization_basis": "geometric_area",
    }
    assert match_product_specific_metric(expected, dict(expected))
    for field, wrong in (
        ("product", "ethylene"),
        ("potential", "-1.00 V RHE"),
        ("reference_electrode", "Ag/AgCl"),
        ("normalization_basis", "catalyst_mass"),
    ):
        observed = dict(expected)
        observed[field] = wrong
        assert not match_product_specific_metric(expected, observed)


def test_stability_association_requires_catalyst_temperature_and_duration():
    expected = {
        "property": "conversion",
        "value": 85,
        "unit": "%",
        "catalyst": "MMONiCo + Ce",
        "temperature": "350 °C",
        "duration": "1400 min",
    }
    assert match_stability_association(expected, dict(expected))
    assert not match_stability_association(expected, {**expected, "catalyst": "MMONiCo"})
    assert not match_stability_association(expected, {key: value for key, value in expected.items() if key != "duration"})


def test_canonical_admission_and_review_contamination_metrics_are_conservative():
    decisions = [
        {"expected": "canonical", "observed": "canonical"},
        {"expected": "quarantine", "observed": "canonical"},
        {"expected": "quarantine", "observed": "quarantine"},
        {"expected": "canonical", "observed": "quarantine"},
    ]
    counts = canonical_admission_counts(decisions)
    assert counts == {
        "true_canonical_admissions": 1,
        "false_canonical_admissions": 1,
        "correct_quarantines": 1,
        "incorrect_quarantines": 1,
        "canonical_precision": 0.5,
    }
    assert canonical_precision(6, 2, 99) == 0.75
    items = [
        {"ownership": "comparison_table", "admission_status": "canonical"},
        {"ownership": "cited_prior_work", "admission_status": "quarantine"},
        {"ownership": "focal_work", "admission_status": "canonical"},
    ]
    assert review_contamination_count(items) == 1


def test_dft_leakage_and_unsupported_potential_conversion_are_detected():
    assert detect_dft_leakage({
        "record_type": "ExperimentRecord",
        "property": "adsorption_free_energy",
        "calculation": {"method": "DFT"},
    })
    assert not detect_dft_leakage({"record_type": "CalculationRecord", "property": "adsorption_free_energy"})
    assert detect_potential_conversion_violation({
        "raw_potential": "-0.80 V vs Ag/AgCl",
        "converted_potential": "-0.60 V vs RHE",
        "conversion_status": "deterministic",
    })
    assert not detect_potential_conversion_violation({
        "raw_potential": "-0.80 V vs Ag/AgCl",
        "converted_potential": "-0.60 V vs RHE",
        "conversion_status": "author_reported",
    })


def test_referential_integrity_reports_every_supported_dangling_reference_kind():
    valid = {
        "catalysts": [
            {"local_id": "cat_a"},
            {"local_id": "cat_b", "variant_of": "cat_a", "state_parent_ref": "cat_a"},
        ],
        "preparations": [{"material_ref": "cat_b"}],
        "characterizations": [{"material_ref": "cat_a"}],
        "heterogeneous_experiments": [{"experiment_id": "exp_a", "catalyst_ref": "cat_b"}],
        "electrocatalysis_experiments": [],
        "stability_tests": [{"experiment_ref": "exp_a", "catalyst_state_ref": "cat_b"}],
        "calculations": [{"material_refs": ["cat_a", "cat_b"]}],
    }
    assert referential_integrity_violations(valid) == []
    valid["stability_tests"][0]["experiment_ref"] = "missing"
    valid["calculations"][0]["material_refs"].append("missing-cat")
    violations = referential_integrity_violations(valid)
    assert len(violations) == 2
    assert any("experiment_ref" in item for item in violations)
    assert any("material_refs[2]" in item for item in violations)
