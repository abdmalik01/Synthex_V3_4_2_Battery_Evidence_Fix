from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmark.biomaterials_v1.build_archive import build_archive
from benchmark.biomaterials_v1.analytics import analytics_rows
from benchmark.biomaterials_v1.offline_recovery import LOCKS, _pages, recover
from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.extraction.biomaterials_contract import (
    COMPUTATIONAL_UNITS, RESULT_UNITS, biomaterials_admission_decision, biomaterials_device_decision,
    biomaterials_result_identity,
)
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction.router import DomainRouter


ROOT = Path(__file__).resolve().parents[1] / "benchmark" / "biomaterials_v1"
PILOT_CASES = ("BIO-GOLD-A", "BIO-BIOACT-B", "BIO-DEGR-C", "BIO-PROCESS-D")


def _gold(case):
    return json.loads((ROOT / LOCKS[case]["gold"]).read_text(encoding="utf-8"))


def _recovered(case):
    return recover(case)["outputs"]


def _as_map(rows):
    return {(r["sample_label"], r["property"], r["context"].get("exposure_time"),
             r["context"].get("organism"), r["context"].get("dilution"),
             r["context"].get("specimen_type")): r["value"] for r in rows}


@pytest.mark.parametrize("case", LOCKS)
def test_locked_pdf_and_gold_before_recovery(case):
    lock = LOCKS[case]
    assert hashlib.sha256((ROOT / lock["pdf"]).read_bytes()).hexdigest() == lock["pdf_sha256"]
    assert hashlib.sha256((ROOT / lock["gold"]).read_bytes()).hexdigest() == lock["gold_sha256"]


@pytest.mark.parametrize("case", LOCKS)
def test_every_verbatim_value_snippet_is_on_cited_pdf_page(case):
    pages = _pages(case)
    for row in _recovered(case):
        evidence = row["evidence"]
        assert evidence["text_snippet"] in pages[evidence["page"] - 1]
        assert row["raw_value"] in evidence["text_snippet"]


def test_gold_a_exact_source_recovery():
    gold = _gold("BIO-GOLD-A")
    rows = _recovered("BIO-GOLD-A")
    actual = _as_map(rows)
    assert len(rows) == gold["gold_output_count"] == 36
    for variant in gold["variants"]:
        label = variant["label"]
        assert actual[label, "pore_size", None, None, None, None] == variant["measured_pore_size_um"]
        assert actual[label, "volume_porosity", None, None, None, None] == variant["volume_porosity_percent"]
        for day, value in zip(gold["viability_times_day"], variant["viability_percent"]):
            assert actual[label, "cell_viability", f"day {day}", None, None, None] == value
        for day, value in zip(gold["proliferation_times_day"], variant["proliferation_ratio"]):
            assert actual[label, "cell_proliferation_ratio", f"day {day}", None, None, None] == value
    archive = build_archive("BIO-GOLD-A")
    assert len(archive.materials) == 1 and len(archive.devices) == 4
    assert {tuple(device.material_ids) for device in archive.devices} == {(archive.materials[0].material_id,)}
    assert all(device.configuration["formulation"] == archive.materials[0].name for device in archive.devices)
    assert "10% w/v gelatin" in archive.materials[0].name and "2% w/v sodium alginate" in archive.materials[0].name
    assert all(device.configuration["encapsulation_density_raw"] for device in archive.devices)
    assert all(out.conditions["replicates"] == gold["replicates"] and out.conditions["culture_temperature_C"] == 37
               for exp in archive.experiments for out in exp.outputs if out.property.startswith("cell_"))


def test_gold_b_exact_source_recovery_and_missing_cells():
    gold = _gold("BIO-BIOACT-B")
    rows = _recovered("BIO-BIOACT-B")
    assert len(rows) == gold["gold_output_count"] == 26
    for variant in gold["variants"]:
        observed = [r for r in rows if r["sample_label"] == variant["label"]]
        assert [r["value"] for r in observed] == [x for x in variant["values"] if x is not None]
        assert all(r["context"]["strain"].startswith("ATCC ") for r in observed)
        assert all("exposure_time" not in r["context"] for r in observed)
        control_for_organism = dict(zip(gold["organisms"], gold["positive_control_mm"]))
        for row in observed:
            organism = row["context"]["organism"] + " " + row["context"]["strain"]
            assert row["context"]["positive_control_mm"] == control_for_organism[organism]
            assert row["context"]["negative_control_status"] == "sterile_water_table_dash_not_zero"


def test_gold_c_exact_endpoints_no_interpolation():
    gold = _gold("BIO-DEGR-C")
    rows = _recovered("BIO-DEGR-C")
    actual = {(r["sample_label"], r["property"]): r for r in rows}
    assert len(rows) == gold["gold_output_count"] == 18
    mapping = {"swelling_percent": "swelling_ratio", "mass_loss_percent": "mass_loss",
               "strut_diameter_um": "strut_diameter", "pore_diameter_um": "pore_diameter",
               "compressive_yield_strength_MPa": "compressive_yield_strength", "elastic_modulus_kPa": "elastic_modulus"}
    for variant in gold["variants"]:
        for field, prop in mapping.items():
            assert actual[variant["label"], prop]["value"] == variant[field]
    assert {r["context"].get("exposure_time") for r in rows if r["property"] == "swelling_ratio"} == {"72 h"}
    assert {r["context"].get("exposure_time") for r in rows if r["property"] == "mass_loss"} == {"28 day"}
    assert all(r["property"] != "degradation_rate" for r in rows)


def test_gold_d_filament_scaffold_process_association():
    gold = _gold("BIO-PROCESS-D")
    rows = _recovered("BIO-PROCESS-D")
    actual = {(r["sample_label"], r["property"], r["context"]["specimen_type"]): r["value"] for r in rows}
    assert len(rows) == gold["gold_output_count"] == 21
    for variant in gold["filament_dsc_table2"]:
        label = variant["label"]
        assert actual[label, "cold_crystallization_temperature", "filament"] == variant["Tcc_C"]
        assert actual[label, "melting_enthalpy", "filament"] == variant["enthalpy_J_g"]
        assert actual[label, "crystallinity", "filament"] == variant["crystallinity_percent"]
    for variant in gold["scaffold_results"]:
        label = variant["label"]
        assert actual[label, "deposited_layer_width", "scaffold"] == variant["deposited_layer_width_um"]
        assert actual[label, "compressive_modulus", "scaffold"] == variant["compressive_modulus_MPa"]
        assert actual[label, "ultimate_compressive_strength", "scaffold"] == variant["ultimate_compressive_strength_MPa"]
    archive = build_archive("BIO-PROCESS-D")
    settings = {p.property: p.value for process in archive.processes for p in process.parameters}
    frozen = gold["printing_parameters"]
    assert settings == {"printing_speed": frozen["printing_speed_mm_s"],
                        "nozzle_temperature": frozen["nozzle_temperature_C"],
                        "bed_temperature": frozen["bed_temperature_C"],
                        "nozzle_diameter": frozen["nozzle_diameter_mm"],
                        "layer_height": frozen["layer_height_mm"],
                        "infill_density": frozen["infill_density_percent"]}
    assert sum(len(process.parameters) for process in archive.processes) == 12  # two printed scaffold variants


@pytest.mark.parametrize("case", PILOT_CASES)
def test_canonical_specimens_experiments_and_graph_are_separate(case):
    archive = build_archive(case)
    gold = _gold(case)
    outputs = [output for experiment in archive.experiments for output in experiment.outputs]
    assert len(outputs) == gold["gold_output_count"]
    expected_materials = 1 if case == "BIO-GOLD-A" else 5 if case == "BIO-PROCESS-D" else len(gold["variants"])
    assert len(archive.materials) == expected_materials
    assert archive.metadata.domain == "biomaterials"
    assert not archive.calculations
    assert not archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    ids = {m.material_id for m in archive.materials} | {d.device_id for d in archive.devices} | {p.process_id for p in archive.processes} | {e.experiment_id for e in archive.experiments} | {archive.metadata.archive_id, archive.sources[0].source_id}
    assert all(rel.subject_id in ids and rel.object_id in ids for rel in archive.relationships)
    assert all(e.device_id in {d.device_id for d in archive.devices} and len(e.material_ids) == 1 for e in archive.experiments)
    assert all(o.evidence and o.evidence[0].page and o.evidence[0].verbatim_match for o in outputs)


def _measurement(prop="cell_viability", **changes):
    context = {"sample_label": "scaffold A", "cell_line": "C3A", "assay": "Live/Dead", "exposure_time": "24 h", "scientific_type": "reported_measurement"}
    context.update(changes)
    return Measurement(property=prop, raw_value="90", value=90, unit="%", method=context.get("assay"), conditions=context,
                       evidence=[Evidence(page=2, source_type=SourceType.table, table_id="Table 1", verbatim_match=True, text_snippet="scaffold A 90")])


@pytest.mark.parametrize("left,right", [
    ("cell_viability", "cell_proliferation_ratio"), ("cell_viability", "cytotoxicity"),
    ("cell_viability", "metabolic_activity"), ("hemolysis", "cell_viability"),
    ("inhibition_zone", "bacterial_viability"), ("cfu_reduction", "log_reduction"),
    ("mass_loss", "degradation_rate"), ("swelling_ratio", "water_uptake"),
    ("water_uptake", "porosity"), ("porosity", "pore_size"),
    ("pore_size", "fiber_diameter"), ("contact_angle", "surface_roughness"),
])
def test_distinct_property_semantics(left, right):
    assert biomaterials_result_identity(_measurement(left)) != biomaterials_result_identity(_measurement(right))


@pytest.mark.parametrize("field,other", [
    ("cell_line", "L929"), ("assay", "MTT"), ("assay", "CCK-8"),
    ("exposure_time", "72 h"), ("sample_label", "scaffold B"),
    ("process", "crosslinked"), ("medium", "PBS"),
    ("organism", "E. coli"), ("strain", "ATCC 25922"),
])
def test_context_dimensions_never_merge(field, other):
    assert biomaterials_result_identity(_measurement()) != biomaterials_result_identity(_measurement(**{field: other}))


def test_missing_cell_context_and_caption_only_are_quarantined():
    missing = _measurement(cell_line=None)
    assert not biomaterials_admission_decision(missing, role="result").admitted
    caption = _measurement()
    caption.evidence[0].source_type = SourceType.figure_caption
    assert not biomaterials_admission_decision(caption, role="result").admitted


def test_non_numeric_missing_value_and_unit_rejected():
    m = _measurement()
    m.raw_value = "-"
    assert not biomaterials_admission_decision(m, role="result").admitted
    m = _measurement()
    m.unit = "MPa"
    assert not biomaterials_admission_decision(m, role="result").admitted


def test_biological_measurement_not_computation():
    m = _measurement(scientific_type="calculated")
    assert not biomaterials_admission_decision(m, role="result", modality="computational").admitted


def test_bactericidal_and_bacteriostatic_not_silently_classified():
    assert not biomaterials_admission_decision(_measurement("bactericidal"), role="result").admitted
    assert not biomaterials_admission_decision(_measurement("bacteriostatic"), role="result").admitted


def test_initial_and_final_mass_not_misclassified_as_mass_loss():
    assert biomaterials_result_identity(_measurement("initial_mass")) != biomaterials_result_identity(_measurement("final_mass"))
    assert not biomaterials_admission_decision(_measurement("initial_mass"), role="result").admitted


@pytest.mark.parametrize("case", PILOT_CASES)
def test_analytics_keep_specimen_assay_and_time_identity(case):
    archive = build_archive(case)
    rows = analytics_rows(archive)
    assert len(rows) == _gold(case)["gold_output_count"]
    assert len({(row["specimen_id"], row["identity"]) for row in rows}) == len(rows)
    assert all(row["evidence_page"] is not None and row["source_id"] == archive.sources[0].source_id for row in rows)


def test_live_preparation_is_source_only_and_does_not_decide_authorization():
    from benchmark.biomaterials_v1.prepare_live import DISCOVERY_DIR, prepare
    plans = [json.loads((ROOT / "live_preparation.json").read_text(encoding="utf-8"))]
    if any(DISCOVERY_DIR.glob("*.json")):
        plans.append(prepare())
    else:
        # A clean checkout has the historical preparation record, not the
        # ignored provider-discovery body needed for a new operational preflight.
        with pytest.raises(ValueError, match="No newly discovered exact Gemini model list"):
            prepare()
    for plan in plans:
        assert plan["source_transmitted_by_preparation"] is False
        assert plan["authorization_status"] == "NOT_EVALUATED_BY_LOCAL_PREPARATION"
        assert len(plan["candidate_exact_models"]) == 3
        assert all(item["gold_used"] == "hash_verification_only" and item["gold_in_prompt"] is False for item in plan["inputs"])


def test_manifest_matches_admission_taxonomy():
    manifest = DomainRegistry().get("biomaterials")
    assert {property_spec["key"] for property_spec in manifest["properties"]} == set(RESULT_UNITS) | set(COMPUTATIONAL_UNITS)


def test_30_interim_scientific_invariants():
    identity = lambda prop, **kw: biomaterials_result_identity(_measurement(prop, **kw))
    archives = {case: build_archive(case) for case in PILOT_CASES}
    a = archives["BIO-GOLD-A"]
    b = archives["BIO-BIOACT-B"]
    c = archives["BIO-DEGR-C"]
    d = archives["BIO-PROCESS-D"]
    all_rows = {case: analytics_rows(archive) for case, archive in archives.items()}
    all_outputs = [out for archive in archives.values() for exp in archive.experiments for out in exp.outputs]
    specimen_ids = {dev.device_id for archive in archives.values() for dev in archive.devices}
    material_ids = {mat.material_id for archive in archives.values() for mat in archive.materials}
    caption = _measurement()
    caption.evidence[0].source_type = SourceType.figure_caption
    missing = _measurement(cell_line=None)
    implant = build_archive("BIO-GOLD-A").devices[0]
    from synthex_platform.extraction.draft_models import DraftDevice, DraftDeviceLayer
    implant_draft = DraftDevice(local_id="implant", device_type="biomaterial_implant",
        configuration={"sample_label": "implant"},
        layer_stack=[DraftDeviceLayer(sequence_index=0, role="bulk_formulation", material_ref="mat",
            evidence=[Evidence(page=1, source_type=SourceType.text, text_snippet="implant", verbatim_match=True)])])
    checks = {
        1: identity("cell_viability") != identity("cell_proliferation_ratio"),
        2: identity("cell_viability") != identity("cytotoxicity"),
        3: identity("cell_viability") != identity("metabolic_activity"),
        4: identity("cell_viability", assay="MTT") != identity("cell_viability", assay="CCK-8"),
        5: identity("cell_viability", cell_line="C3A") != identity("cell_viability", cell_line="L929"),
        6: identity("cell_viability", exposure_time="24 h") != identity("cell_viability", exposure_time="72 h"),
        7: identity("hemolysis") != identity("cell_viability"),
        8: identity("inhibition_zone") != identity("bacterial_viability"),
        9: identity("cfu_reduction") != identity("log_reduction"),
        10: not biomaterials_admission_decision(_measurement("bactericidal"), role="result").admitted
            and not biomaterials_admission_decision(_measurement("bacteriostatic"), role="result").admitted,
        11: identity("mass_loss") != identity("degradation_rate"),
        12: identity("swelling_ratio") != identity("water_uptake"),
        13: identity("water_uptake") != identity("porosity"),
        14: identity("initial_mass") != identity("final_mass"),
        15: identity("porosity") != identity("pore_size"),
        16: identity("pore_size") != identity("fiber_diameter"),
        17: identity("contact_angle") != identity("surface_roughness"),
        18: specimen_ids.isdisjoint(material_ids) and all(dev.material_ids for archive in archives.values() for dev in archive.devices),
        19: biomaterials_device_decision(implant_draft).admitted and implant.device_type == "biomaterial_scaffold",
        20: all(out.conditions.get("assay") for exp in a.experiments for out in exp.outputs if out.property.startswith("cell_")),
        21: all(out.conditions.get("organism") and out.conditions.get("strain") for exp in b.experiments for out in exp.outputs),
        22: all(out.conditions.get("cell_line") for exp in a.experiments for out in exp.outputs if out.property.startswith("cell_")),
        23: all(out.conditions.get("exposure_time") for out in all_outputs if out.property in {"cell_viability", "cell_proliferation_ratio", "swelling_ratio", "mass_loss"}),
        24: len(a.materials) == 1 and len(a.devices) == 4 and len(b.materials) == 5 and len(c.materials) == 3 and len(d.materials) == 5,
        25: len({proc.name for proc in a.processes}) == 2 and sum(bool(proc.parameters) for proc in d.processes) == 2,
        26: not biomaterials_admission_decision(missing, role="result").admitted
            and all("exposure_time" not in out.conditions for exp in b.experiments for out in exp.outputs),
        27: len(all_rows["BIO-BIOACT-B"]) == 26 and {r["conditions"].get("exposure_time") for r in all_rows["BIO-DEGR-C"] if r["property"] == "mass_loss"} == {"28 day"},
        28: not biomaterials_admission_decision(caption, role="result").admitted,
        29: all(len({(row["specimen_id"], row["identity"]) for row in rows}) == len(rows) for rows in all_rows.values()),
        30: all(archive.metadata.domain == "biomaterials" and not archive.calculations and
                all(exp.device_id in {dev.device_id for dev in archive.devices} for exp in archive.experiments)
                for archive in archives.values()),
    }
    assert len(checks) == 30
    assert all(checks.values()), f"Failed Biomaterials invariants: {[number for number, passed in checks.items() if not passed]}"


@pytest.mark.parametrize("text,expected", [
    ("Cell-laden hydrogel scaffold tested with C3A cell viability and cell proliferation", "biomaterials"),
    ("Antimicrobial hydrogel wound dressing has inhibition zone against E. coli", "biomaterials"),
    ("PLA-Mn scaffold for tissue engineering with stem cell viability and compressive strength", "biomaterials"),
    ("Polymer membrane CO2/CH4 gas separation selectivity and gas permeance in barrer", "membranes"),
    ("Steel tensile testing with yield strength and ultimate tensile strength", "mechanical"),
])
def test_domain_routing_safety(text, expected):
    assert DomainRouter().route_text(text).domain == expected


def test_live_runner_rejects_unapproved_case_model_and_retry_count_before_provider_use():
    from benchmark.biomaterials_v1.run_live import run_case

    missing_discovery = Path("no-discovery-needed-for-rejection.json")
    with pytest.raises(ValueError, match="Unapproved Biomaterials live case"):
        run_case("BIO-DEGR-C", "models/gemini-3.8-flash", missing_discovery)
    with pytest.raises(ValueError, match="Unapproved exact Gemini model"):
        run_case("BIO-GOLD-A", "models/gemini-flash-latest", missing_discovery)
    with pytest.raises(ValueError, match="At most three"):
        run_case("BIO-GOLD-A", "models/gemini-3.8-flash", missing_discovery, max_attempts=4)


def test_live_runner_counts_interrupted_attempts_across_approved_cases(tmp_path, monkeypatch):
    from benchmark.biomaterials_v1 import run_live

    monkeypatch.setattr(run_live, "OUTPUT", tmp_path)
    for case in ("BIO-GOLD-A", "BIO-BIOACT-B"):
        path = tmp_path / case / "attempt-1" / "attempt_metadata.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"model": "models/gemini-3.7-flash", "case_id": case}), encoding="utf-8")
    assert run_live._prior_attempt_count("models/gemini-3.7-flash") == 2
    with pytest.raises(ValueError, match="model-wide budget exceeded"):
        run_live.run_case("BIO-GOLD-A", "models/gemini-3.7-flash", tmp_path / "missing.json", max_attempts=2)


@pytest.mark.parametrize("case_id,expected", [("BIO-GOLD-A", 36), ("BIO-BIOACT-B", 26)])
def test_conservative_raw_scorer_preserves_biological_context(case_id, expected):
    from benchmark.biomaterials_v1.build_archive import build_draft
    from benchmark.biomaterials_v1.score_persisted_raw import score_raw_case

    raw = build_draft(case_id).model_dump(mode="json")
    score = score_raw_case(raw, _gold(case_id))
    assert score["expected_points"] == expected
    assert score["exact_value_unit_context_points"] == expected
    assert score["page_evidence_points"] == expected
    assert score["direct_focal_ownership_points"] == expected

    output = next(output for experiment in raw["experiments"] for output in experiment["outputs"]
                  if case_id != "BIO-GOLD-A" or output["property"] == "cell_viability")
    output["conditions"]["assay"] = "wrong assay"
    changed = score_raw_case(raw, _gold(case_id))
    assert changed["exact_value_unit_context_points"] == expected - 1
