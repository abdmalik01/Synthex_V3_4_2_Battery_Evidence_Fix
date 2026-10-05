"""Append-only, semantics-preserving replay of four historical Gemini payloads.

This is a structural normalization, not an evidence repair. It never consults
gold while transforming content and never rewrites any provider artifact.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re

from pydantic import ValidationError

from synthex_platform.benchmarks.provider_artifacts import _io_path
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import ExtractedDocument

from .score_persisted_raw import _number, score_raw_case
from .source_tables import ROOT, resolve_run_artifact_root, source_lock


VERSION = "semiconductor_provider_normalizer_v1"
ARTIFACTS = (
    "normalization_audit_v1.json", "normalized_candidate_v1.json",
    "normalized_validation_v1.json", "normalized_scientific_score_v1.json",
    "normalized_admission_v1.json",
)


def _read(path: Path) -> str:
    return _io_path(path).read_text(encoding="utf-8")


def _json(path: Path) -> dict:
    return json.loads(_read(path))


def _evidence(value: object) -> list[dict]:
    if isinstance(value, str):
        value = [{"snippet": value}]
    elif isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    result = []
    allowed = {"source_id", "page", "section", "source_type", "original_source_type",
               "verbatim_match", "text_snippet", "table_id", "figure_id", "locator", "confidence"}
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized = {key: item[key] for key in allowed if key in item}
        if "snippet" in item and "text_snippet" not in normalized:
            normalized["text_snippet"] = item["snippet"]
        if "page" not in normalized:
            match = re.search(r"(?:^|;)page=(\d+)(?:;|$)", str(item.get("locator", "")))
            if match:
                normalized["page"] = int(match[1])
        # A provider's snippet is not a PDF-verified verbatim match.
        normalized.pop("verbatim_match", None)
        result.append(normalized)
    return result


def _measurement(item: dict) -> dict:
    prop = item.get("property") or item.get("property_key") or item.get("canonical_key") or item.get("name")
    raw = item.get("raw_value", item.get("value"))
    conditions = dict(item.get("conditions")) if isinstance(item.get("conditions"), dict) else {}
    for key in ("material_ref", "experiment_ref", "process_ref"):
        if key in item:
            conditions[f"provider_{key}"] = item[key]
    result = {"property": prop, "raw_value": str(raw) if raw is not None else None,
              "value": _number(raw), "unit": item.get("unit"), "conditions": conditions,
              "evidence": _evidence(item.get("evidence"))}
    source = item.get("source")
    if isinstance(source, dict):
        result["evidence"].extend(_evidence(source))
    if isinstance(item.get("evidence"), str) and item.get("locator"):
        result["evidence"][0].update({"locator": item["locator"],
                                      "source_type": item.get("source_type", "unknown"),
                                      "original_source_type": item.get("original_source_type")})
    if item.get("normalized_value") is not None:
        result["normalized_value"] = item["normalized_value"]
    if item.get("method") is not None:
        result["method"] = item["method"]
    return result


def normalize_raw(raw: dict) -> tuple[dict, dict, list[str]]:
    """Return strict draft, independent flat scoring view, and applied rules."""
    rules = ["field_alias_formula_to_formula", "field_alias_property_key_to_property",
             "field_alias_canonical_key_to_property", "field_alias_snippet_to_text_snippet",
             "preserve_explicit_object_associations", "no_semantic_property_aliasing",
             "no_page_or_verbatim_evidence_invention"]
    materials = []
    for item in raw.get("materials", []):
        if not isinstance(item, dict) or not item.get("local_id"):
            continue
        materials.append({"local_id": item["local_id"], "name": item.get("name"),
                          "formula": item.get("formula") or item.get("chemical_formula") or item.get("composition_formula"),
                          "ownership": item.get("ownership", "unknown"),
                          "evidence": _evidence(item.get("evidence")),
                          "tags": item.get("tags", []) if isinstance(item.get("tags"), list) else []})
    records = next((raw[key] for key in ("derived_properties", "measurements", "properties")
                    if isinstance(raw.get(key), list)), [])
    normalized_records = []
    for item in records:
        if not isinstance(item, dict):
            continue
        transformed = dict(item)
        transformed["property"] = item.get("property") or item.get("property_key") or item.get("canonical_key")
        if isinstance(item.get("evidence"), list):
            transformed["evidence"] = _evidence(item["evidence"])
        normalized_records.append(transformed)
    experiments = []
    for item in raw.get("experiments", []):
        if not isinstance(item, dict) or not item.get("local_id"):
            continue
        local_id = item["local_id"]
        outputs = [_measurement(record) for record in records if isinstance(record, dict)
                   and record.get("experiment_ref") == local_id]
        experiments.append({"local_id": local_id,
                            "experiment_type": item.get("experiment_type") or item.get("type") or item.get("technique") or item.get("name") or "unknown",
                            "material_refs": item.get("material_refs") or item.get("measured_materials") or [],
                            "ownership": item.get("ownership", "unknown"),
                            "evidence": _evidence(item.get("evidence")), "outputs": outputs})
    processes = []
    for item in raw.get("processes", []):
        if not isinstance(item, dict) or not item.get("local_id"):
            continue
        processes.append({"local_id": item["local_id"],
                          "name": item.get("name") or item.get("process_type") or item.get("type") or "unknown",
                          "family": item.get("family") or item.get("process_type") or item.get("type"),
                          "material_refs": item.get("material_refs", []),
                          "input_material_refs": item.get("input_material_refs", []),
                          "output_material_refs": item.get("output_material_refs", []),
                          "parameters": [_measurement(p) for p in item.get("parameters", []) if isinstance(p, dict)],
                          "ownership": item.get("ownership", "unknown"),
                          "evidence": _evidence(item.get("evidence"))})
    draft = {"source": raw.get("source", {}) if isinstance(raw.get("source"), dict) else {},
             "materials": materials, "processes": processes, "experiments": experiments,
             "devices": [], "calculations": [],
             "domain_values": {"provider_unmapped_top_level_keys": sorted(set(raw) -
                               {"source", "materials", "processes", "experiments", "devices", "calculations",
                                "derived_properties", "measurements", "properties", "document_id"}),
                               "provider_document_id": raw.get("document_id")}}
    scoring_view = {"materials": materials, "measurements": normalized_records}
    return draft, scoring_view, rules


def _categories(errors: list[dict], raw: dict) -> dict[str, int]:
    categories = {key: 0 for key in (
        "property_key_naming", "scientific_subtype_loss", "nesting", "measurement_grouping",
        "sample_association", "process_association", "evidence_representation",
        "condition_representation", "ownership_placement", "required_field_omission",
        "type_mismatch", "repeated_object_structure", "repair_specific_failure")}
    for error in errors:
        loc = [str(part) for part in error.get("loc", [])]
        joined = ".".join(loc)
        kind = error.get("type")
        if kind == "missing": categories["required_field_omission"] += 1
        if kind and ("type" in kind or kind in {"list_type", "dict_type"}): categories["type_mismatch"] += 1
        if "property" in joined or "canonical_key" in joined: categories["property_key_naming"] += 1
        if "evidence" in joined or "source" in joined or "locator" in joined: categories["evidence_representation"] += 1
        if "conditions" in joined: categories["condition_representation"] += 1
        if "ownership" in joined: categories["ownership_placement"] += 1
        if "processes" in joined: categories["process_association"] += 1
        if "experiments" in joined: categories["measurement_grouping"] += 1
        if "materials" in joined: categories["sample_association"] += 1
        if kind == "extra_forbidden": categories["nesting"] += 1
    if any(key in raw for key in ("derived_properties", "measurements", "properties")):
        categories["nesting"] += 1
    if any(len(value) > 1 for key, value in raw.items() if key in {"materials", "processes", "experiments"} and isinstance(value, list)):
        categories["repeated_object_structure"] += 1
    return categories


def _write_exclusive(path: Path, payload: dict) -> None:
    with _io_path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write("\n")


def normalize_run(history: dict) -> dict:
    root = resolve_run_artifact_root(history["artifact_run_root"])
    attempt = next((root / f"attempt-{i}" for i in range(1, 4)
                    if _io_path(root / f"attempt-{i}" / "raw_response.txt").is_file()), None)
    if attempt is None:
        raise ValueError(f"No persisted raw response: {history['run_id']}")
    raw_bytes = _io_path(attempt / "raw_response.txt").read_bytes()
    raw_sha = sha256(raw_bytes).hexdigest()
    if raw_sha != history["raw_response_sha256"]:
        raise ValueError(f"Historical raw hash mismatch: {history['run_id']}")
    raw = _json(attempt / "parsed_response.json")
    gold = _json(ROOT / source_lock(history["case_id"])["gold_file"])
    before = score_raw_case(raw, gold)
    if before["exact_value_and_unit_points"] != history["raw_scientific_score"]["exact_value_and_unit_points"]:
        raise ValueError("Original raw score changed")
    draft_data, scoring_view, rules = normalize_raw(raw)
    after = score_raw_case(scoring_view, gold)
    try:
        draft = ExtractedDocument.model_validate(draft_data)
        schema_errors = []
        admitted = assemble_archive(draft, domain="semiconductors", model=VERSION)
        canonical_outputs = sum(len(exp.outputs) for exp in admitted.experiments) + sum(len(calc.outputs) for calc in admitted.calculations)
        quarantined = admitted.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    except ValidationError as error:
        schema_errors = error.errors(include_url=False)
        canonical_outputs = 0
        quarantined = []
    source_errors = _json(attempt / "raw_validation_report.json").get("errors", [])
    audit = {"schema": "synthex.semiconductors.normalization_audit.v1", "normalizer_version": VERSION,
             "case_id": history["case_id"], "provider": "gemini", "exact_model": history["model_id"],
             "run_id": history["run_id"], "raw_sha256": raw_sha, "applied_rules": rules,
             "deliberately_not_normalized": ["generic mobility to Hall mobility", "electron concentration to carrier concentration",
                                          "missing measurement temperature", "missing table cells", "missing page-verbatim evidence",
                                          "missing specimen or process states", "unreported calculations"],
             "raw_schema_failure_categories": _categories(source_errors, raw),
             "raw_schema_error_count": len(source_errors),
             "property_key_score_before": before["exact_property_key_points"],
             "property_key_score_after": after["exact_property_key_points"]}
    candidate = {"schema": "synthex.semiconductors.normalized_candidate.v1", "normalizer_version": VERSION,
                 "case_id": history["case_id"], "run_id": history["run_id"], "raw_sha256": raw_sha,
                 "draft": draft_data, "scoring_view": scoring_view}
    validation = {"schema_valid": not schema_errors, "errors": schema_errors,
                  "source_raw_schema_valid": history["schema_valid"]}
    scientific = {"raw_score": {key: before[key] for key in ("exact_value_and_unit_points", "exact_property_key_points",
                                                    "expected_points", "exact_sample_count", "page_locator_points",
                                                    "verbatim_snippet_points", "direct_focal_ownership_points")},
                  "normalized_score": {key: after[key] for key in ("exact_value_and_unit_points", "exact_property_key_points",
                                                        "expected_points", "exact_sample_count", "page_locator_points",
                                                        "verbatim_snippet_points", "direct_focal_ownership_points")},
                  "no_value_growth": after["exact_value_and_unit_points"] <= before["exact_value_and_unit_points"]}
    admission = {"canonical_admission": False, "canonical_outputs": canonical_outputs,
                 "quarantined_object_count": len(quarantined),
                 "reason": "Missing provider-supplied, PDF-verified page-verbatim evidence; no source or gold grafting permitted."}
    if canonical_outputs:
        raise ValueError("Normalizer unexpectedly produced canonical outputs")
    payloads = (audit, candidate, validation, scientific, admission)
    if any(_io_path(root / filename).exists() for filename in ARTIFACTS):
        raise FileExistsError(f"Append-only normalization artifact already exists: {root}")
    for filename, payload in zip(ARTIFACTS, payloads):
        _write_exclusive(root / filename, payload)
    if sha256(_io_path(attempt / "raw_response.txt").read_bytes()).hexdigest() != raw_sha:
        raise ValueError("Raw response mutated during normalization")
    return {"case_id": history["case_id"], "model": history["model_id"], "run_id": history["run_id"],
            "schema_valid": validation["schema_valid"], "before": scientific["raw_score"],
            "after": scientific["normalized_score"], "canonical_admission": False,
            "raw_sha256": raw_sha, "normalization_artifacts": list(ARTIFACTS)}


def normalize_all() -> list[dict]:
    gate = _json(ROOT / "live_gate.json")
    if not gate["SEM_LIVE_GATE_SATISFIED"]:
        raise ValueError("Historical live gate is not satisfied")
    return [normalize_run(history) for history in gate["runs"]]


if __name__ == "__main__":
    print(json.dumps(normalize_all(), indent=2, ensure_ascii=True))
