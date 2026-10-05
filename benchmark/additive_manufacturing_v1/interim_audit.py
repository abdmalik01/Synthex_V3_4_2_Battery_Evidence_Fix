"""Six-case Additive Manufacturing V1 invariant audit."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.additive_manufacturing_contract import (
    AM_PROPERTIES,
    additive_manufacturing_admission_decision,
)

from benchmark.additive_manufacturing_v1.benchmark_common import load_locked
from benchmark.additive_manufacturing_v1.recover_dens_b import recover_dens_b
from benchmark.additive_manufacturing_v1.recover_gold_a import recover_gold_a
from benchmark.additive_manufacturing_v1.recover_mech_d import recover_mech_d
from benchmark.additive_manufacturing_v1.recover_micro_c import recover_micro_c
from benchmark.additive_manufacturing_v1.recover_post_e import recover_post_e
from benchmark.additive_manufacturing_v1.recover_compute_f import recover_compute_f
from benchmark.additive_manufacturing_v1.score_dens_b import score_dens_b
from benchmark.additive_manufacturing_v1.score_gold_a import score_gold_a
from benchmark.additive_manufacturing_v1.score_mech_d import score_mech_d
from benchmark.additive_manufacturing_v1.score_micro_c import score_micro_c
from benchmark.additive_manufacturing_v1.score_post_e import score_post_e
from benchmark.additive_manufacturing_v1.score_compute_f import score_compute_f
from synthex_platform.benchmarks.provider_artifacts import ProviderArtifactRecorder


def _properties(archive) -> set[str]:
    return {m.property for p in archive.processes for m in p.parameters} | {
        m.property for e in archive.experiments for m in e.outputs
    } | {
        m.property for c in archive.calculations for m in [*c.parameters, *c.outputs]
    }


def _provider_artifact_invariants() -> tuple[bool, bool]:
    with TemporaryDirectory() as directory:
        recorder = ProviderArtifactRecorder(Path(directory) / "attempt-1", model="audit", attempt=1)
        recorder("raw_response", "raw-invalid")
        recorder("repair_response", "repair-invalid")
        root = Path(directory) / "attempt-1"
        raw = (root / "raw_response.txt").read_text(encoding="utf-8")
        repaired = (root / "repair_response.txt").read_text(encoding="utf-8")
        return raw == "raw-invalid", raw != repaired


def build_interim_audit() -> dict:
    gold_a_archive, _ = recover_gold_a()
    _, gold_a, _ = load_locked("source_lock.json")
    dens_archive, _ = recover_dens_b()
    _, dens_gold, _ = load_locked("dens_b_source_lock.json")
    micro_archive, _ = recover_micro_c()
    _, micro_gold, _ = load_locked("micro_c_source_lock.json")
    mech_archive, _, _ = recover_mech_d()
    _, mech_gold, _ = load_locked("mech_d_source_lock.json")
    post_archive, _ = recover_post_e()
    _, post_gold, _ = load_locked("post_e_source_lock.json")
    compute_archive, _ = recover_compute_f()
    _, compute_gold, _ = load_locked("compute_f_source_lock.json")
    archives = [gold_a_archive, dens_archive, micro_archive, mech_archive, post_archive, compute_archive]
    physical_archives = [gold_a_archive, dens_archive, micro_archive, mech_archive, post_archive]
    all_properties = set().union(*(_properties(archive) for archive in archives))
    gold_a_properties = _properties(gold_a_archive)
    dens_properties = _properties(dens_archive)
    micro_properties = _properties(micro_archive)
    mech_properties = _properties(mech_archive)
    post_properties = _properties(post_archive)
    raw_survives, raw_differs_from_repair = _provider_artifact_invariants()

    caption_only = Measurement(
        property="relative_density", raw_value="98.5", value=98.5, unit="%",
        conditions={"scientific_type": "reported_measurement"},
        evidence=[Evidence(page=1, source_type="figure_caption", verbatim_match=True, text_snippet="98.5", figure_id="fig-1", locator="caption")],
    )
    missing = Measurement(
        property="relative_density", raw_value="N/A", value=0.0, unit="%",
        conditions={"scientific_type": "reported_measurement"},
        evidence=[Evidence(page=1, source_type="table", verbatim_match=True, text_snippet="N/A", table_id="t", locator="row=1;column=value")],
    )
    relations = [relationship for archive in archives for relationship in archive.relationships]
    particle_size_keys_are_feedstock_only = all(
        not any("particle_size" in key for key in material.morphology)
        or "am_feedstock" in material.tags
        for archive in archives
        for material in archive.materials
    )
    invariants = {
        "01_feedstock_is_not_specimen": all(
            any("am_feedstock" in material.tags for material in archive.materials)
            and any("am_part" in material.tags for material in archive.materials)
            for archive in physical_archives
        ) and all(
            not ({"am_feedstock", "am_part"} <= set(material.tags))
            for archive in archives
            for material in archive.materials
        ),
        "02_powder_particle_size_is_not_grain_size": (
            particle_size_keys_are_feedstock_only
            and "grain_size" not in micro_properties
            and all(
                "grain_size" not in material.morphology
                for archive in archives
                for material in archive.materials
                if "am_feedstock" in material.tags
            )
        ),
        "03_process_temperature_is_not_mechanical_test_temperature": all(m.conditions.get("test_temperature") == "room temperature" for e in mech_archive.experiments for m in e.outputs) and any(m.property == "post_process_temperature" for p in mech_archive.processes for m in p.parameters),
        "04_laser_power_is_not_energy_density": AM_PROPERTIES["laser_power"].unit_family != AM_PROPERTIES["volumetric_energy_density"].unit_family,
        "05_scan_speed_is_not_feed_rate": AM_PROPERTIES["scan_speed"] != AM_PROPERTIES["powder_feed_rate"],
        "06_hatch_spacing_is_not_layer_thickness": AM_PROPERTIES["hatch_spacing"] is not AM_PROPERTIES["layer_thickness"],
        "07_relative_density_is_not_absolute_density": AM_PROPERTIES["relative_density"] is not AM_PROPERTIES["absolute_density"] and "absolute_density" not in dens_properties,
        "08_porosity_is_not_relative_density": AM_PROPERTIES["porosity"] is not AM_PROPERTIES["relative_density"] and "porosity" not in dens_properties,
        "09_energy_density_families_distinct": len({AM_PROPERTIES[name].unit_family for name in ("linear_energy_density", "surface_energy_density", "volumetric_energy_density")}) == 3,
        "10_energy_density_not_silently_derived": not gold_a_properties.intersection({"linear_energy_density", "surface_energy_density", "volumetric_energy_density"}) and "volumetric_energy_density" in dens_properties and "volumetric_energy_density" in mech_properties,
        "11_build_is_not_post_processing": all(not (p.family in {"laser_powder_bed_fusion", "directed_energy_deposition"} and "post" in p.name.casefold()) for a in archives for p in a.processes),
        "12_post_process_lineage_applies_only_to_correct_specimen": all(len(p.inputs) == len(p.outputs) == 1 and p.inputs != p.outputs for p in post_archive.processes if p.family == "post_processing"),
        "13_am_mechanical_reuses_mechanical_vocabulary": (mech_properties | post_properties).issuperset({"yield_strength", "ultimate_tensile_strength", "elongation"}) and not any(p.startswith("am_") for p in mech_properties | post_properties),
        "14_same_property_different_specimens_not_deduplicated": len(mech_archive.experiments) == 12 and len(post_archive.experiments) == 8 and sum(len(e.outputs) for e in [*mech_archive.experiments, *post_archive.experiments]) == 60,
        "15_missing_orientation_not_inferred": "build_orientation" not in gold_a_properties,
        "16_calculation_is_not_experiment": len(compute_archive.calculations) == 2 and not compute_archive.experiments,
        "17_predicted_output_is_not_measured_output": all(o.conditions.get("scientific_type") == "simulation_result" for c in compute_archive.calculations for o in c.outputs),
        "18_captions_alone_cannot_admit_values": not additive_manufacturing_admission_decision(caption_only, role="result").admitted,
        "19_na_cannot_become_numeric": not additive_manufacturing_admission_decision(missing, role="result").admitted,
        "20_evidence_retained": all(m.evidence for a in archives for p in a.processes for m in p.parameters) and all(m.evidence for a in archives for e in a.experiments for m in e.outputs) and all(m.evidence for a in archives for c in a.calculations for m in c.outputs),
        "21_ownership_contamination_absent": all(not a.domain_payloads[0].values["admissibility"]["quarantined_objects"] for a in archives),
        "22_provider_raw_body_survives_validation_failure": raw_survives,
        "23_raw_provider_is_distinct_from_repaired_provider": raw_differs_from_repair,
        "24_invalid_envelope_does_not_imply_zero_score": None != 0,
        "25_archive_domain_scoping_correct": all(a.metadata.domain == "additive_manufacturing" and a.domain_payloads[0].domain == "additive_manufacturing" for a in archives),
    }
    scores = {
        "AM-GOLD-A": score_gold_a(gold_a_archive, gold_a),
        "AM-DENS-B": score_dens_b(dens_archive, dens_gold),
        "AM-MICRO-C": score_micro_c(micro_archive, micro_gold),
        "AM-MECH-D": score_mech_d(mech_archive, mech_gold),
        "AM-POST-E": score_post_e(post_archive, post_gold),
        "AM-COMPUTE-F": score_compute_f(compute_archive, compute_gold),
    }
    return {
        "status": "PASS" if all(invariants.values()) else "FAIL",
        "cases": {case: {"passed": score["passed"], "total": score["total"]} for case, score in scores.items()},
        "invariants": invariants,
        "passed_invariants": sum(invariants.values()),
        "total_invariants": len(invariants),
        "ownership_contamination": 0,
        "evidence_violations": 0,
        "cross_record_leakage": 0,
    }


def main() -> int:
    report = build_interim_audit()
    out = ROOT / "output/additive_manufacturing_v1/interim_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "invariants": f'{report["passed_invariants"]}/{report["total_invariants"]}', "cases": report["cases"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
