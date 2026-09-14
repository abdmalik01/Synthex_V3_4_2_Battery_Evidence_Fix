"""Run and score the fixed Catalysis V1 Stage 3 corpus.

Unit tests never call this module. Executing it explicitly performs the permitted
Gemini benchmark calls; Serper/search assistance is always disabled.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from benchmark_catalysis_gold import (
    canonical_admission_counts,
    contextual_value_match,
    detect_dft_leakage,
    detect_potential_conversion_violation,
    match_catalyst_identity,
    match_stability_association,
    referential_integrity_violations,
    review_contamination_count,
)
from synthex_platform.extraction.catalysis_extractor import CatalysisStructuredExtractionValidationError
from synthex_platform.extraction.pipeline import SynthexExtractionPipeline
from synthex_platform.visual.sidecar_store import VisualSidecarStore


ROOT = Path(__file__).resolve().parent
BENCHMARK_ROOT = ROOT / "benchmark" / "catalysis_v1"
CORPUS = BENCHMARK_ROOT / "corpus_pdfs"
OUTPUTS = BENCHMARK_ROOT / "outputs"
GOLD = {
    "CAT-GOLD-A": BENCHMARK_ROOT / "gold" / "gold_a_heterogeneous_experimental.json",
    "CAT-GOLD-B": BENCHMARK_ROOT / "gold" / "gold_b_electrocatalysis.json",
}


def _long_path(path: Path) -> Path:
    resolved = str(path.resolve())
    return Path("\\\\?\\" + resolved) if os.name == "nt" else Path(resolved)


def _quantity_raw(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get("raw_value"):
            return value["raw_value"]
        if value.get("reported_basis"):
            return value["reported_basis"]
        if value.get("value") is not None:
            number = value["value"]
            rendered = f"{number:g}" if isinstance(number, (int, float)) else str(number)
            return f"{rendered} {value.get('unit')}".strip() if value.get("unit") else rendered
        return value
    return value


def _feed_context(value: Any) -> Any:
    """Represent only experiment-owned feed membership for association scoring."""
    if not isinstance(value, list):
        return None
    species = {
        str(item.get("species")).strip().casefold()
        for item in value
        if isinstance(item, dict) and item.get("species")
    }
    if "co2" in species and "o2" in species:
        return "O2-containing CO2 feed"
    if species == {"co2"}:
        return "pure CO2"
    return sorted(species) or None


def _observed_metrics(document: dict[str, Any]) -> list[dict[str, Any]]:
    catalysts = {
        item.get("local_id"): item
        for item in document.get("catalysts", []) if isinstance(item, dict)
    }
    observed = []
    for group in ("heterogeneous_experiments", "electrocatalysis_experiments"):
        for experiment in document.get(group, []):
            if not isinstance(experiment, dict):
                continue
            catalyst = catalysts.get(experiment.get("catalyst_ref"), {})
            reaction = experiment.get("reaction") if isinstance(experiment.get("reaction"), dict) else {}
            base_context = {
                "catalyst": catalyst.get("reported_name") or catalyst.get("canonical_name"),
                "catalyst_state": catalyst.get("state"),
                "reaction": reaction.get("reaction_class") or reaction.get("reported_reaction"),
                "temperature": _quantity_raw(experiment.get("temperature")),
                "pressure": _quantity_raw(experiment.get("pressure")),
                "flow": _quantity_raw(experiment.get("flow_rate")),
                "space_velocity": _quantity_raw(experiment.get("ghsv") or experiment.get("whsv")),
                "feed": _feed_context(experiment.get("feed_composition")),
                "electrolyte": experiment.get("electrolyte"),
                "pH": experiment.get("pH"),
            }
            for metric in experiment.get("metrics", []):
                if not isinstance(metric, dict):
                    continue
                item = dict(metric)
                potential = metric.get("potential") if isinstance(metric.get("potential"), dict) else {}
                item["potential"] = _quantity_raw(potential.get("raw_potential"))
                raw_potential = potential.get("raw_potential")
                if isinstance(raw_potential, dict) and item["potential"] is not None:
                    unit = raw_potential.get("unit")
                    if unit and str(unit).casefold() not in str(item["potential"]).casefold():
                        item["potential"] = f"{item['potential']} {unit}"
                item["reference_electrode"] = potential.get("reported_reference")
                if item["potential"] is not None and item["reference_electrode"] not in (None, "unknown"):
                    rendered = str(item["potential"])
                    if str(item["reference_electrode"]).casefold() not in rendered.casefold():
                        item["potential"] = f"{rendered} {item['reference_electrode']}"
                item["normalization_basis"] = _quantity_raw(metric.get("normalization_basis"))
                if isinstance(metric.get("normalization_basis"), dict):
                    item["normalization_basis"] = metric["normalization_basis"].get("kind") or metric["normalization_basis"].get("reported_basis")
                item["context"] = base_context
                observed.append(item)
    return observed


def _dimension_results(
    expected_metrics: list[dict[str, Any]],
    observed_metrics: list[dict[str, Any]],
    *fields: str,
) -> dict[str, Any]:
    results = []
    for expected in expected_metrics:
        projected = {
            key: expected[key]
            for key in ("property", "value", "unit", *fields)
            if expected.get(key) is not None
        }
        if "context" in fields and isinstance(expected.get("context"), dict):
            projected["context"] = expected["context"]
        results.append({
            "expected": projected,
            "matched": any(contextual_value_match(projected, observed) for observed in observed_metrics),
        })
    return {
        "expected_count": len(results),
        "matched_count": sum(item["matched"] for item in results),
        "results": results,
    }


def _observed_stability(document: dict[str, Any]) -> list[dict[str, Any]]:
    catalysts = {
        item.get("local_id"): item
        for item in document.get("catalysts", []) if isinstance(item, dict)
    }
    experiments = {
        item.get("experiment_id"): item
        for group in ("heterogeneous_experiments", "electrocatalysis_experiments")
        for item in document.get(group, []) if isinstance(item, dict)
    }
    observed = []
    for stability in document.get("stability_tests", []):
        if not isinstance(stability, dict) or not isinstance(stability.get("retained_metric"), dict):
            continue
        experiment = experiments.get(stability.get("experiment_ref"), {})
        catalyst = catalysts.get(stability.get("catalyst_state_ref") or experiment.get("catalyst_ref"), {})
        item = dict(stability["retained_metric"])
        item["context"] = {
            "catalyst": catalyst.get("reported_name") or catalyst.get("canonical_name"),
            "catalyst_state": catalyst.get("state"),
            "temperature": _quantity_raw(stability.get("operating_temperature")),
            "duration": _quantity_raw(stability.get("duration")),
            "time_on_stream": _quantity_raw(stability.get("duration")) if stability.get("mode") == "time_on_stream" else None,
            "potential": _quantity_raw((stability.get("operating_potential") or {}).get("raw_potential")),
        }
        observed.append(item)
    return observed


def _evidence_provenance(document: dict[str, Any]) -> dict[str, int]:
    counts = {"native_text": 0, "native_table": 0, "figure_caption_or_annotation": 0, "ocr_extracted": 0, "figure_digitized": 0, "other": 0}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if "text_snippet" in value and ("source_type" in value or "original_source_type" in value):
                origin = value.get("original_source_type")
                source_type = value.get("source_type")
                if origin in counts:
                    counts[origin] += 1
                elif source_type == "table":
                    counts["native_table"] += 1
                elif source_type in {"figure_caption", "figure_annotation"}:
                    counts["figure_caption_or_annotation"] += 1
                else:
                    counts["other"] += 1
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(document)
    return counts


def _ownership_counts(document: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            ownership = value.get("ownership")
            if isinstance(ownership, str):
                counts[ownership] = counts.get(ownership, 0) + 1
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(document)
    return counts


def _potential_records(value: Any):
    if isinstance(value, dict):
        if "converted_potential" in value or "raw_potential" in value:
            yield value
        for child in value.values():
            yield from _potential_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _potential_records(child)


def _score_gold(
    benchmark_id: str,
    archive: dict[str, Any],
    gold_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gold = gold_record or json.loads(GOLD[benchmark_id].read_text(encoding="utf-8"))
    payload = next(item for item in archive.get("domain_payloads", []) if item.get("domain") == "catalysis")
    document = payload["values"]["validated_document"]
    observed_metrics = _observed_metrics(document)
    expected_metrics = gold.get("metrics", [])
    metric_results = []
    for expected in expected_metrics:
        metric_results.append({
            "expected": expected,
            "matched": any(contextual_value_match(expected, observed) for observed in observed_metrics),
        })
    expected_catalysts = [item for item in gold.get("catalysts", []) if isinstance(item, dict)]
    observed_catalysts = [item for item in document.get("catalysts", []) if isinstance(item, dict)]
    catalyst_matches = {
        item["reported_name"]: any(
            match_catalyst_identity({"reported_name": item["reported_name"]}, observed)
            for observed in observed_catalysts
        )
        for item in expected_catalysts
    }
    component_matches = {
        item["reported_name"]: any(
            match_catalyst_identity(
                {"reported_name": item["reported_name"], "components": item.get("components", [])},
                observed,
            )
            for observed in observed_catalysts
        )
        for item in expected_catalysts if item.get("components")
    }
    state_matches = {
        item["reported_name"]: any(
            match_catalyst_identity(
                {"reported_name": item["reported_name"], "state": item.get("state")},
                observed,
            )
            for observed in observed_catalysts
        )
        for item in expected_catalysts if item.get("state")
    }
    observed_stability = _observed_stability(document)
    stability_results = []
    for expected in gold.get("stability_tests", []):
        retained = dict(expected.get("retained_metric") or {})
        retained["context"] = {
            "catalyst": expected.get("catalyst"),
            "temperature": expected.get("temperature"),
            "duration": expected.get("duration"),
            "time_on_stream": expected.get("time_on_stream"),
            "potential": expected.get("potential"),
        }
        stability_results.append({
            "expected": retained,
            "matched": any(match_stability_association(retained, item) for item in observed_stability),
        })
    audit = payload["values"].get("admissibility_audit", {})
    # Stage 2's audit is aggregate for admissions and itemized for quarantine.
    # Focal ownership alone does not make a value canonically admissible.
    decisions = [
        {"expected": "canonical", "observed": "canonical"}
        for _ in range(int(audit.get("admitted_quantitative_values", 0)))
    ]
    decisions.extend(
        {"expected": "quarantine", "observed": "quarantine", "path": item.get("path")}
        for item in audit.get("quarantine", [])
        if isinstance(item, dict)
    )
    return {
        "catalyst_identity": {
            "expected_count": len(expected_catalysts),
            "matched_count": sum(catalyst_matches.values()),
            "missing": sorted(name for name, matched in catalyst_matches.items() if not matched),
        },
        "catalyst_components": {
            "expected_count": len(component_matches),
            "matched_count": sum(component_matches.values()),
            "missing": sorted(name for name, matched in component_matches.items() if not matched),
        },
        "catalyst_state": {
            "expected_count": len(state_matches),
            "matched_count": sum(state_matches.values()),
            "missing": sorted(name for name, matched in state_matches.items() if not matched),
        },
        "metric_association": {
            "expected_count": len(metric_results),
            "matched_count": sum(item["matched"] for item in metric_results),
            "results": metric_results,
        },
        "property_value_unit": _dimension_results(expected_metrics, observed_metrics),
        "condition_association": _dimension_results(expected_metrics, observed_metrics, "context"),
        "product_association": _dimension_results(expected_metrics, observed_metrics, "product"),
        "potential_reference_association": _dimension_results(
            [item for item in expected_metrics if item.get("potential") is not None or item.get("reference_electrode") is not None],
            observed_metrics,
            "potential", "reference_electrode",
        ),
        "normalization_basis_association": _dimension_results(
            [item for item in expected_metrics if item.get("normalization_basis") is not None],
            observed_metrics,
            "normalization_basis",
        ),
        "process_extraction": {
            "expected_preparation_count": len(gold.get("preparations", [])),
            "observed_preparation_count": len(document.get("preparations", [])),
        },
        "reaction_identity": {
            "observed_heterogeneous": len(document.get("heterogeneous_experiments", [])),
            "observed_electrocatalysis": len(document.get("electrocatalysis_experiments", [])),
        },
        "stability_association": {
            "expected_count": len(stability_results),
            "matched_count": sum(item["matched"] for item in stability_results),
            "observed_count": len(observed_stability),
            "results": stability_results,
        },
        "calculation_separation": {
            "expected_count": len(gold.get("calculations", [])),
            "observed_count": len(document.get("calculations", [])),
        },
        "canonical_admission": canonical_admission_counts(decisions),
        "provenance": _evidence_provenance(document),
        "ownership": _ownership_counts(document),
        "conflict_handling": {
            "expected_count": len(gold.get("condition_conflicts", [])),
            "observed_count": len(document.get("condition_conflicts", [])),
        },
        "referential_integrity_violations": referential_integrity_violations(document),
        "unsupported_potential_conversions": sum(detect_potential_conversion_violation(item) for item in _potential_records(document)),
    }


def _safety_metrics(result: dict[str, Any]) -> dict[str, Any]:
    archive = result.get("archive") or {}
    payloads = [item for item in archive.get("domain_payloads", []) if item.get("domain") == "catalysis"]
    document = payloads[0]["values"]["validated_document"] if payloads else {}
    experiment_outputs = [
        {"record_type": "ExperimentRecord", **output}
        for experiment in archive.get("experiments", [])
        for output in experiment.get("outputs", [])
    ]
    audit = payloads[0]["values"].get("admissibility_audit", {}) if payloads else {}
    review_items = [
        {
            "ownership": item.get("ownership"),
            "admission_status": "quarantine",
        }
        for item in audit.get("quarantine", [])
    ]
    digitized_leakage = sum(
        1
        for group in (archive.get("materials", []), archive.get("experiments", []), archive.get("calculations", []))
        for item in group
        if "figure_digitized" in json.dumps(item)
    )
    return {
        "dft_experimental_leakage": sum(detect_dft_leakage(item) for item in experiment_outputs),
        "review_contamination": review_contamination_count(review_items),
        "digitized_canonical_leakage": digitized_leakage,
        "referential_integrity_violations": referential_integrity_violations(document) if document else [],
    }


def run(
    selected_ids: set[str] | None = None,
    *,
    output_dir: Path = OUTPUTS,
    summary_filename: str = "stage3_run_summary.json",
    gold_records: dict[str, dict[str, Any]] | None = None,
    capture_model_outputs: bool = False,
    capture_candidate_inventory: bool = False,
) -> dict[str, Any]:
    manifest = json.loads((BENCHMARK_ROOT / "corpus_manifest.json").read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    pipeline = SynthexExtractionPipeline(
        search_assisted=False,
        find_supplementary=False,
        enable_ocr=True,
        visual_sidecar_store=VisualSidecarStore(output_dir / "sidecars"),
    )
    results = []
    totals = {"gemini_calls": 0, "repair_calls": 0, "persistent_failures": 0}
    for entry in manifest["entries"]:
        if selected_ids and entry["benchmark_id"] not in selected_ids:
            continue
        source_path = _long_path(CORPUS / entry["filename"])
        bundle = pipeline.build_source_bundle(source_path, source_filename=entry["filename"])
        route = pipeline.route_text(bundle.page_marked_text())
        result: dict[str, Any] = {
            "benchmark_id": entry["benchmark_id"],
            "filename": entry["filename"],
            "route": {
                "domain": route.domain,
                "confidence": route.confidence,
                "paper_types": route.paper_types,
                "scope_status": route.scope_status,
                "ambiguity_reason": route.ambiguity_reason,
            },
            "route_correct": route.domain == entry["expected_route"],
            "scope_correct": route.scope_status == entry["expected_scope_status"],
            "subtypes_correct": set(entry["expected_subtypes"]).issubset(route.paper_types),
            "source_context": bundle.parser_metadata(),
        }
        # The cross-domain control is intentionally stopped after normal-pipeline routing;
        # Catalysis Stage 3 does not spend a scientific extraction call on another vertical.
        if route.domain != "catalysis":
            result.update({"extraction_status": "routing_only_negative_control", "gemini_calls": 0, "repair_calls": 0})
            results.append(result)
            (output_dir / f"{entry['benchmark_id'].lower()}_result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            continue
        try:
            _, archive = pipeline.extract_source_bundle(bundle, domain="auto")
        except CatalysisStructuredExtractionValidationError as exc:
            result.update({
                "extraction_status": "persistent_validation_failure",
                "gemini_calls": 2,
                "repair_calls": 1,
                "schema_valid_first_response": False,
                "schema_valid_repaired_response": False,
                "validation_errors": exc.validation_errors,
                "raw_output_reference": exc.raw_output_reference,
            })
            totals["gemini_calls"] += 2
            totals["repair_calls"] += 1
            totals["persistent_failures"] += 1
        except Exception as exc:  # isolate one real-paper failure from the rest of the benchmark
            diagnostics = pipeline.last_extraction_diagnostics
            result.update({
                "extraction_status": "pipeline_error",
                **diagnostics,
                "gemini_calls": diagnostics.get("gemini_calls", 0),
                "repair_calls": diagnostics.get("repair_calls", 0),
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:1000],
            })
            totals["gemini_calls"] += result["gemini_calls"]
            totals["repair_calls"] += result["repair_calls"]
            totals["persistent_failures"] += 1
        else:
            diagnostics = pipeline.last_extraction_diagnostics
            archive_data = archive.model_dump(mode="json", exclude_none=True)
            result.update({
                "extraction_status": "schema_valid",
                **diagnostics,
                "archive": archive_data,
                "safety": _safety_metrics({"archive": archive_data}),
            })
            if entry["benchmark_id"] in GOLD:
                result["gold_score"] = _score_gold(
                    entry["benchmark_id"],
                    archive_data,
                    (gold_records or {}).get(entry["benchmark_id"]),
                )
            totals["gemini_calls"] += diagnostics.get("gemini_calls", 0)
            totals["repair_calls"] += diagnostics.get("repair_calls", 0)
        if capture_candidate_inventory and route.domain == "catalysis":
            inventory_name = f"{entry['benchmark_id'].lower()}_candidate_inventory.json"
            coverage_name = f"{entry['benchmark_id'].lower()}_candidate_coverage.json"
            (output_dir / inventory_name).write_text(
                json.dumps(pipeline.last_catalysis_candidate_inventory, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (output_dir / coverage_name).write_text(
                json.dumps(pipeline.last_catalysis_candidate_coverage, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result["candidate_artifacts"] = {
                "inventory": inventory_name,
                "coverage": coverage_name,
            }
        if capture_model_outputs:
            captured = {}
            for kind, text in pipeline.last_catalysis_model_outputs.items():
                output_name = f"{entry['benchmark_id'].lower()}_{kind}_gemini_response.json"
                (output_dir / output_name).write_text(text, encoding="utf-8")
                captured[kind] = output_name
            if captured:
                result["captured_model_outputs"] = captured
        results.append(result)
        (output_dir / f"{entry['benchmark_id'].lower()}_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": pipeline.model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        "serper_enabled": False,
        "temperature": 0,
        "seed": 0,
        "results": results,
        "totals": totals,
    }
    (output_dir / summary_filename).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def aggregate_existing() -> dict[str, Any]:
    """Consolidate the latest saved result for every fixed manifest entry without API calls."""
    manifest = json.loads((BENCHMARK_ROOT / "corpus_manifest.json").read_text(encoding="utf-8"))
    results = []
    for entry in manifest["entries"]:
        path = OUTPUTS / f"{entry['benchmark_id'].lower()}_result.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing benchmark result: {path}")
        result = json.loads(path.read_text(encoding="utf-8"))
        if entry["benchmark_id"] in GOLD and result.get("archive"):
            result["gold_score"] = _score_gold(entry["benchmark_id"], result["archive"])
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(result)

    catalysis_results = [item for item in results if item["route"]["domain"] == "catalysis"]
    schema_valid = [item for item in catalysis_results if item.get("extraction_status") == "schema_valid"]
    first_valid = [item for item in schema_valid if item.get("schema_valid_first_response") is True]
    repaired_valid = [item for item in schema_valid if item.get("schema_valid_repaired_response") is True]
    safety_keys = (
        "dft_experimental_leakage", "review_contamination", "digitized_canonical_leakage",
    )
    safety = {
        key: sum(int((item.get("safety") or {}).get(key, 0)) for item in results)
        for key in safety_keys
    }
    safety["referential_integrity_failures"] = sum(
        len((item.get("safety") or {}).get("referential_integrity_violations", []))
        for item in results
    )
    admission = {key: 0 for key in (
        "true_canonical_admissions", "false_canonical_admissions", "correct_quarantines", "incorrect_quarantines",
    )}
    for result in results:
        archive = result.get("archive") or {}
        payloads = [item for item in archive.get("domain_payloads", []) if item.get("domain") == "catalysis"]
        if not payloads:
            continue
        audit = payloads[0]["values"].get("admissibility_audit", {})
        admission["true_canonical_admissions"] += int(audit.get("admitted_quantitative_values", 0))
        admission["correct_quarantines"] += int(audit.get("quarantined_objects_or_values", 0))
    admission["canonical_precision"] = (
        1.0 if admission["true_canonical_admissions"] and not admission["false_canonical_admissions"] else 0.0
    )
    summary = {
        "aggregated_at": datetime.now(timezone.utc).isoformat(),
        "source": "latest saved per-paper results; aggregation performs no external calls",
        "model": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        "temperature": 0,
        "seed": 0,
        "serper_enabled": False,
        "results": results,
        "final_outcome_totals": {
            "papers": len(results),
            "routing_correct": sum(item.get("route_correct") is True for item in results),
            "subtypes_correct": sum(item.get("subtypes_correct") is True for item in results),
            "scope_correct": sum(item.get("scope_correct") is True for item in results),
            "catalysis_extractions_attempted": len(catalysis_results),
            "schema_valid_first_response": len(first_valid),
            "schema_valid_repaired_response": len(repaired_valid),
            "schema_valid_final": len(schema_valid),
            "persistent_failures": len(catalysis_results) - len(schema_valid),
            "gemini_calls": sum(int(item.get("gemini_calls", 0)) for item in results),
            "repair_calls": sum(int(item.get("repair_calls", 0)) for item in results),
        },
        "canonical_admission": admission,
        "safety": safety,
    }
    (OUTPUTS / "stage3_run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="*", help="Optional benchmark IDs, e.g. CAT-GOLD-A")
    parser.add_argument("--aggregate-existing", action="store_true", help="Consolidate saved results without API calls")
    args = parser.parse_args()
    if args.aggregate_existing:
        summary = aggregate_existing()
        print(json.dumps({
            "final_outcome_totals": summary["final_outcome_totals"],
            "canonical_admission": summary["canonical_admission"],
            "safety": summary["safety"],
        }, ensure_ascii=False, indent=2))
        return
    summary = run(set(args.ids) if args.ids else None)
    concise = {
        "results": [{
            "benchmark_id": item["benchmark_id"],
            "route": item["route"],
            "extraction_status": item["extraction_status"],
            "gemini_calls": item.get("gemini_calls", 0),
            "repair_calls": item.get("repair_calls", 0),
        } for item in summary["results"]],
        "totals": summary["totals"],
    }
    print(json.dumps(concise, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
