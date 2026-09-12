from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pypdf import PdfReader

from benchmark_battery_material import evaluate as evaluate_li2fetio4
from synthex_platform.extraction import BatteryGeminiExtractor, assemble_battery_archive
from synthex_platform.extraction.router import DomainRouter
from synthex_v2.pdf_utils_v2 import extract_pages, pages_to_marked_text


REPO_ROOT = Path(__file__).resolve().parent
CORPUS_DIR = REPO_ROOT / "benchmark" / "batteries_v1" / "corpus_pdfs"
MANIFEST_PATH = REPO_ROOT / "benchmark" / "batteries_v1" / "corpus_manifest.json"
OUTPUT_DIR = REPO_ROOT / "benchmark" / "outputs" / "corpus"

# Frozen before the run: seven unique in-domain documents and one hard negative.
SELECTED_FILES = (
    "batteries-11-00142.pdf",
    "batteries-11-00011.pdf",
    "1-s2.0-S2666386426002407-main.pdf",
    "Evaluation_of_Li_Ion_Batteries.pdf",
    "ZiebertEEVC2017ATable-drivenLIBModelforaBMSdevelopmentplatform.pdf",
    "Application_of_First_Principles_Computations_Based.pdf",
    "coatings-16-00912.pdf",
    "applsci-10-04112.pdf",
)

EXPECTED_PAPER_TYPES = {
    "batteries-11-00142.pdf": {
        "materials_synthesis", "electrode_fabrication", "cell_assembly",
        "electrochemical_performance", "impedance_eis",
    },
    "batteries-11-00011.pdf": {"impedance_eis", "battery_dataset_modelling"},
    "1-s2.0-S2666386426002407-main.pdf": {"impedance_eis", "battery_dataset_modelling"},
    "Evaluation_of_Li_Ion_Batteries.pdf": {
        "battery_dataset_modelling", "electrochemical_performance",
        "degradation_health", "impedance_eis",
    },
    "ZiebertEEVC2017ATable-drivenLIBModelforaBMSdevelopmentplatform.pdf": {
        "battery_dataset_modelling",
    },
    "Application_of_First_Principles_Computations_Based.pdf": {"computational_dft"},
}


def _slug(filename: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", Path(filename).stem.lower()).strip("_")


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _manifest_entry(manifest: dict[str, Any], filename: str) -> dict[str, Any]:
    return next(entry for entry in manifest["entries"] if entry["filename"] == filename)


def _metadata_fallback(pdf_path: Path, manifest_entry: dict[str, Any]) -> str:
    """Provide labelled routing-only text if normal PDF extraction cannot run."""
    title = manifest_entry.get("title") or pdf_path.stem
    try:
        reader = PdfReader(str(pdf_path))
        title = str((reader.metadata or {}).get("/Title") or title)
    except Exception:
        pass
    return f"TITLE: {title}"


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _walk_evidence(document: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(value: Any, location: str) -> None:
        if isinstance(value, dict):
            if "evidence" in value:
                evidence = value.get("evidence") or []
                if isinstance(evidence, dict):
                    evidence = [evidence]
                found.append({"location": location, "evidence": evidence})
            for key, item in value.items():
                if key != "evidence":
                    walk(item, f"{location}.{key}" if location else key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{location}[{index}]")

    walk(document, "")
    return found


def _provenance_metrics(document: dict[str, Any], source_text: str) -> dict[str, Any]:
    records = _walk_evidence(document)
    normalized_source = _normalize_text(source_text)
    supported = 0
    snippets = 0
    unmatched: list[dict[str, Any]] = []
    records_with_verbatim = 0
    verified_snippets = 0
    without_evidence: list[str] = []
    source_types: Counter[str] = Counter()
    for record in records:
        evidence = record["evidence"]
        if not evidence:
            without_evidence.append(record["location"])
            continue
        supported += 1
        record_has_verbatim = False
        for item in evidence:
            source_types[str(item.get("source_type") or "unknown")] += 1
            snippet = item.get("text_snippet")
            if not snippet:
                continue
            snippets += 1
            if item.get("verbatim_match") is True:
                verified_snippets += 1
                record_has_verbatim = True
            else:
                unmatched.append({
                    "location": record["location"],
                    "page": item.get("page"),
                    "snippet": snippet,
                })
        if record_has_verbatim:
            records_with_verbatim += 1
    return {
        "evidence_capable_records": len(records),
        "records_with_evidence": supported,
        "record_coverage": round(supported / max(len(records), 1), 3),
        "records_with_verbatim_evidence": records_with_verbatim,
        "verbatim_record_coverage": round(records_with_verbatim / max(len(records), 1), 3),
        "snippets_checked": snippets,
        "verbatim_match_coverage": round(verified_snippets / max(snippets, 1), 3),
        "unmatched_snippet_candidates": unmatched,
        "records_without_evidence": without_evidence,
        "source_type_counts": dict(source_types),
    }


def _performance_duplicates(document: dict[str, Any]) -> list[dict[str, Any]]:
    indexed: dict[tuple[Any, ...], list[str]] = {}
    for group in document.get("battery_groups", []):
        for point in group.get("performance_points", []):
            signature = (
                group.get("material_ref"), group.get("variant_label"),
                point.get("property"), point.get("value"), point.get("unit"),
                point.get("cycle"), point.get("c_rate"), point.get("voltage_window"),
                json.dumps(point.get("temperature"), sort_keys=True), point.get("method"),
            )
            indexed.setdefault(signature, []).append(group.get("group_id"))
    return [
        {"signature": list(signature), "groups": groups, "count": len(groups)}
        for signature, groups in indexed.items() if len(groups) > 1
    ]


def _condition_review_candidates(document: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for group in document.get("battery_groups", []):
        for point in group.get("performance_points", []):
            reasons = []
            prop = point.get("property")
            if prop == "capacity_retention" and point.get("cycle") is None:
                reasons.append("retention has no associated cycle")
            if prop == "specific_capacity" and point.get("cycle") is None and point.get("c_rate") is None:
                reasons.append("capacity has neither cycle nor C-rate association")
            if prop in {"charge_transfer_resistance", "impedance", "diffusion_coefficient"} and not point.get("method"):
                reasons.append("impedance/transport value has no method association")
            if reasons:
                candidates.append({
                    "group_id": group.get("group_id"), "property": prop,
                    "value": point.get("value"), "unit": point.get("unit"),
                    "reasons": reasons,
                })
    return candidates


def _coercion_candidates(raw_text: str) -> dict[str, Any]:
    aliases = {
        "loading", "pressing", "dimensions", "drying", "format",
        "glovebox_atmosphere", "o2_limit", "h2o_limit", "cycle_count",
        "voltage_window",
    }
    result = {"recognized_alias_keys": [], "invalid_qualifiers": [], "compact_quantity_strings": 0}
    try:
        raw = json.loads(raw_text)
    except Exception:
        return result

    def walk(value: Any, location: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                path = f"{location}.{key}" if location else key
                if key in aliases:
                    result["recognized_alias_keys"].append(path)
                if key == "qualifier" and item not in {
                    "exact", "approx", "lower_bound", "upper_bound", "range", "unknown",
                }:
                    result["invalid_qualifiers"].append({"location": path, "value": item})
                walk(item, path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{location}[{index}]")
        elif isinstance(value, str) and re.search(r"[-+]?\d+(?:\.\d+)?\s*[A-Za-z%Ωµ°]", value):
            result["compact_quantity_strings"] += 1

    walk(raw, "")
    return result


def _missing_fields(filename: str, document: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    actual_types = set(document.get("paper_types", []))
    for paper_type in sorted(EXPECTED_PAPER_TYPES.get(filename, set()) - actual_types):
        missing.append(f"expected paper_type absent: {paper_type}")
    groups = document.get("battery_groups", [])
    if "materials_synthesis" in EXPECTED_PAPER_TYPES.get(filename, set()):
        if not document.get("materials"):
            missing.append("no material records")
        if not any((m.get("synthesis") or {}).get("method") for m in document.get("materials", [])):
            missing.append("no synthesis method")
    if "impedance_eis" in EXPECTED_PAPER_TYPES.get(filename, set()):
        protocols = document.get("shared_protocols", []) + groups
        if not any(p.get("impedance_protocol") for p in protocols):
            missing.append("no EIS protocol")
    if "electrochemical_performance" in EXPECTED_PAPER_TYPES.get(filename, set()):
        if not any(g.get("performance_points") for g in groups):
            missing.append("no quantitative performance points")
    return missing


def _review_contamination(entry: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    is_review = "review" in str(entry.get("document_type", ""))
    performance_count = sum(len(g.get("performance_points", [])) for g in document.get("battery_groups", []))
    synthesized_materials = sum(bool(m.get("synthesis")) for m in document.get("materials", []))
    return {
        "is_review": is_review,
        "performance_points": performance_count,
        "materials_with_synthesis": synthesized_materials,
        "manual_review_required": bool(is_review and (performance_count or synthesized_materials)),
        "note": (
            "Structured focal-looking facts in a review may originate from cited literature; inspect evidence manually."
            if is_review and (performance_count or synthesized_materials) else None
        ),
    }


def _archive_quantitative_metrics(archive: dict[str, Any]) -> dict[str, Any]:
    measurements: list[tuple[str, dict[str, Any]]] = []
    for process in archive.get("processes", []):
        measurements.extend(("process_parameter", item) for item in process.get("parameters", []))
    for experiment in archive.get("experiments", []):
        measurements.extend(("experiment_condition", item) for item in experiment.get("conditions", []))
        measurements.extend(("scientific_output", item) for item in experiment.get("outputs", []))
    for calculation in archive.get("calculations", []):
        measurements.extend(("calculation_parameter", item) for item in calculation.get("parameters", []))
        measurements.extend(("scientific_output", item) for item in calculation.get("outputs", []))
    quantitative = [
        (kind, item) for kind, item in measurements
        if isinstance(item.get("value"), (int, float)) and not isinstance(item.get("value"), bool)
    ]
    signatures: dict[str, list[str]] = {}
    output_signatures: dict[str, list[str]] = {}
    for kind, item in quantitative:
        signature = json.dumps({
            "property": item.get("property"), "value": item.get("value"),
            "unit": item.get("unit"), "conditions": item.get("conditions", {}),
        }, sort_keys=True)
        signatures.setdefault(signature, []).append(item.get("property"))
        if kind == "scientific_output":
            output_signatures.setdefault(signature, []).append(item.get("property"))
    return {
        "canonical_quantitative_values": len(quantitative),
        "verbatim_supported_values": sum(
            any(evidence.get("verbatim_match") is True for evidence in item.get("evidence", []))
            for _, item in quantitative
        ),
        "duplicate_measurement_signatures": sum(len(items) - 1 for items in signatures.values() if len(items) > 1),
        "duplicate_scientific_output_signatures": sum(
            len(items) - 1 for items in output_signatures.values() if len(items) > 1
        ),
    }


def main() -> None:
    global OUTPUT_DIR
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run the controlled Batteries V1 corpus batch.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--files", nargs="*", choices=SELECTED_FILES)
    parser.add_argument(
        "--resume", action="store_true",
        help="Retain completed reports in corpus_run_state.json and replace only the selected files.",
    )
    args = parser.parse_args()
    OUTPUT_DIR = args.output_dir if args.output_dir.is_absolute() else REPO_ROOT / args.output_dir
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    router = DomainRouter()

    # This process must not make enrichment calls during scoring.
    os.environ["SERPER_QUERY_BUDGET"] = "0"
    os.environ.pop("SERPER_API_KEY", None)

    selected_files = tuple(args.files) if args.files else SELECTED_FILES
    state_path = OUTPUT_DIR / "corpus_run_state.json"
    if args.resume and state_path.exists():
        batch = json.loads(state_path.read_text(encoding="utf-8"))
        selected_names = set(selected_files)
        batch["papers"] = [paper for paper in batch.get("papers", []) if paper.get("filename") not in selected_names]
        batch.pop("summary", None)
        batch.pop("finished_at_unix", None)
        batch["resumed_at_unix"] = time.time()
    else:
        batch = {
            "corpus": manifest["corpus_name"],
            "selected_files": list(SELECTED_FILES),
            "schema_frozen": True,
            "serper_disabled": True,
            "started_at_unix": time.time(),
            "papers": [],
        }
    _json_write(OUTPUT_DIR / "corpus_run_state.json", batch)

    extractor: BatteryGeminiExtractor | None = None
    for index, filename in enumerate(selected_files, start=1):
        print(f"[{index}/{len(selected_files)}] {filename}", flush=True)
        entry = _manifest_entry(manifest, filename)
        pdf_path = CORPUS_DIR / filename
        slug = _slug(filename)
        report: dict[str, Any] = {
            "filename": filename,
            "manifest": entry,
            "expected_domain": "non_battery" if entry.get("document_type") == "non_battery" else "batteries",
            "status": "started",
            "failure_class": None,
            "serper_disabled": True,
        }
        source_text = ""
        try:
            pages = extract_pages(pdf_path)
            source_text = pages_to_marked_text(pages)
            report["pdf_text_extraction"] = {
                "success": True, "pages": len(pages), "prompt_characters": len(source_text),
                "parser": pages[0].get("parser") if pages else None,
                "truncated_at_180000": len(source_text) >= 180_000,
                "table_markers": len(re.findall(r"\btable\s+\d+", source_text, re.I)),
                "figure_markers": len(re.findall(r"\bfig(?:ure)?\.?\s+\d+", source_text, re.I)),
            }
            route_input = source_text
            route_input_kind = "extracted_pdf_text"
        except Exception as exc:
            report["pdf_text_extraction"] = {
                "success": False, "error_type": type(exc).__name__, "error": str(exc),
            }
            report["failure_class"] = "PDF extraction problem"
            route_input = _metadata_fallback(pdf_path, entry)
            route_input_kind = "metadata_title_fallback"

        try:
            route = router.route_text(route_input)
            report["routing"] = {
                **route.__dict__,
                "input_kind": route_input_kind,
                "correct": (
                    route.domain != "batteries"
                    if report["expected_domain"] == "non_battery"
                    else route.domain == "batteries"
                ),
            }
        except Exception as exc:
            report["routing"] = {
                "domain": None, "correct": False, "input_kind": route_input_kind,
                "error_type": type(exc).__name__, "error": str(exc),
            }

        if report["expected_domain"] == "non_battery" and report["routing"].get("domain") != "batteries":
            report.update({
                "status": "correctly_rejected_negative_control",
                "schema_validation_success": None,
                "extractor_skipped": "Correct non-battery route; battery extraction is not applicable.",
            })
            _json_write(OUTPUT_DIR / f"{slug}_report.json", report)
            batch["papers"].append(report)
            _json_write(OUTPUT_DIR / "corpus_run_state.json", batch)
            continue

        if not report["pdf_text_extraction"]["success"]:
            report.update({
                "status": "pdf_extraction_failed_before_gemini",
                "schema_validation_success": None,
                "extractor_skipped": "Existing BatteryGeminiExtractor cannot run without extract_pages output.",
            })
            _json_write(OUTPUT_DIR / f"{slug}_report.json", report)
            batch["papers"].append(report)
            _json_write(OUTPUT_DIR / "corpus_run_state.json", batch)
            continue

        if extractor is None:
            extractor = BatteryGeminiExtractor()
        captured: dict[str, str] = {}
        original_generate = extractor.client.models.generate_content

        def capture_generate(*args: Any, **kwargs: Any) -> Any:
            response = original_generate(*args, **kwargs)
            captured["text"] = response.text or ""
            return response

        try:
            with patch.object(extractor.client.models, "generate_content", side_effect=capture_generate):
                document = extractor.extract_text(source_text)
            raw_text = captured.get("text", "")
            (OUTPUT_DIR / f"{slug}_raw_model_output.json").write_text(raw_text, encoding="utf-8")
            parser_name = pages[0].get("parser") if pages else None
            document._pdf_parser = parser_name
            document.source.pdf_text_parser = parser_name
            archive = assemble_battery_archive(document, model=extractor.model, source_text=source_text)
            document_dict = document.model_dump(exclude_none=True)
            _json_write(OUTPUT_DIR / f"{slug}_extracted_document.json", document_dict)
            archive_dict = archive.model_dump(exclude_none=True)
            _json_write(OUTPUT_DIR / f"{slug}_archive.json", archive_dict)
            admissibility = archive_dict["domain_payloads"][0]["values"]["admissibility"]
            quantitative_metrics = _archive_quantitative_metrics(archive_dict)

            report.update({
                "status": "completed",
                "model": extractor.model,
                "schema_validation_success": True,
                "extraction": {
                    "paper_types": document_dict.get("paper_types", []),
                    "materials": len(document_dict.get("materials", [])),
                    "shared_protocols": len(document_dict.get("shared_protocols", [])),
                    "battery_groups": len(document_dict.get("battery_groups", [])),
                    "performance_points": sum(
                        len(g.get("performance_points", [])) for g in document_dict.get("battery_groups", [])
                    ),
                    "archive_completeness": archive_dict.get("quality", {}).get("completeness"),
                    "archive_semantic_warnings": archive_dict.get("quality", {}).get("semantic_warnings", []),
                    "missing_fields": _missing_fields(filename, document_dict),
                },
                "coercion_candidates": _coercion_candidates(raw_text),
                "provenance": _provenance_metrics(document_dict, source_text),
                "duplicate_facts": _performance_duplicates(document_dict),
                "condition_association_review": _condition_review_candidates(document_dict),
                "review_contamination": _review_contamination(entry, document_dict),
                "admissibility": admissibility,
                "canonical_quantitative_metrics": quantitative_metrics,
                "calculations": len(archive_dict.get("calculations", [])),
                "calculation_outputs": sum(len(item.get("outputs", [])) for item in archive_dict.get("calculations", [])),
                "unresolved_condition_conflicts": sum(
                    conflict.get("status") == "conflicted" and conflict.get("resolved_value") is None
                    for group in document_dict.get("battery_groups", [])
                    for conflict in group.get("condition_conflicts", [])
                ),
                "referential_integrity_warnings": [
                    warning for warning in archive_dict.get("quality", {}).get("semantic_warnings", [])
                    if "unknown material_ref" in warning or "unknown protocol_ref" in warning
                ],
            })
            if report["review_contamination"]["is_review"]:
                report["review_contamination"]["canonical_quantitative_values"] = (
                    quantitative_metrics["canonical_quantitative_values"]
                )
            if filename == "batteries-11-00142.pdf":
                report["manual_gold"] = evaluate_li2fetio4(document)
        except Exception as exc:
            raw_text = captured.get("text", "")
            if raw_text:
                (OUTPUT_DIR / f"{slug}_raw_model_output.txt").write_text(raw_text, encoding="utf-8")
            error_text = str(exc)
            (OUTPUT_DIR / f"{slug}_error.txt").write_text(error_text, encoding="utf-8")
            report.update({
                "status": "failed",
                "schema_validation_success": False if "Pydantic validation" in error_text else None,
                "error_type": type(exc).__name__,
                "error": error_text[:20_000],
                "failure_class": (
                    "one-off LLM formatting variation"
                    if "Pydantic validation" in error_text else "external service failure"
                ),
                "coercion_candidates": _coercion_candidates(raw_text) if raw_text else None,
            })

        _json_write(OUTPUT_DIR / f"{slug}_report.json", report)
        batch["papers"].append(report)
        _json_write(OUTPUT_DIR / "corpus_run_state.json", batch)

    batch["finished_at_unix"] = time.time()
    batch["summary"] = {
        "routing_correct": sum(bool(p.get("routing", {}).get("correct")) for p in batch["papers"]),
        "routing_total": len(batch["papers"]),
        "schema_success": sum(p.get("schema_validation_success") is True for p in batch["papers"]),
        "schema_attempted": sum(p.get("schema_validation_success") is not None for p in batch["papers"]),
        "completed_archives": sum(p.get("status") == "completed" for p in batch["papers"]),
        "pdf_extraction_failures": sum(not p.get("pdf_text_extraction", {}).get("success", False) for p in batch["papers"]),
        "negative_controls_correctly_rejected": sum(
            p.get("status") == "correctly_rejected_negative_control" for p in batch["papers"]
        ),
        "admitted_quantitative_values": sum(
            p.get("admissibility", {}).get("admitted_quantitative_values", 0) for p in batch["papers"]
        ),
        "quarantined_quantitative_values": sum(
            p.get("admissibility", {}).get("quarantined_quantitative_values", 0) for p in batch["papers"]
        ),
        "canonical_quantitative_values": sum(
            p.get("canonical_quantitative_metrics", {}).get("canonical_quantitative_values", 0)
            for p in batch["papers"]
        ),
        "duplicate_canonical_measurements": sum(
            p.get("canonical_quantitative_metrics", {}).get("duplicate_measurement_signatures", 0)
            for p in batch["papers"]
        ),
        "duplicate_canonical_scientific_outputs": sum(
            p.get("canonical_quantitative_metrics", {}).get("duplicate_scientific_output_signatures", 0)
            for p in batch["papers"]
        ),
        "calculations": sum(p.get("calculations", 0) for p in batch["papers"]),
        "calculation_outputs": sum(p.get("calculation_outputs", 0) for p in batch["papers"]),
        "unresolved_condition_conflicts": sum(
            p.get("unresolved_condition_conflicts", 0) for p in batch["papers"]
        ),
        "referential_integrity_warnings": sum(
            len(p.get("referential_integrity_warnings", [])) for p in batch["papers"]
        ),
        "review_canonical_quantitative_values": sum(
            p.get("review_contamination", {}).get("canonical_quantitative_values", 0)
            for p in batch["papers"]
        ),
    }
    _json_write(OUTPUT_DIR / "corpus_report.json", batch)
    print(json.dumps(batch["summary"], indent=2), flush=True)


if __name__ == "__main__":
    main()
