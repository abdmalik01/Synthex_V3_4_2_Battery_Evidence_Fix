"""Conservative scoring of the original immutable A/B Gemini response only.

Scientific matches do not imply schema validity or canonical admission.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import re

from synthex_platform.benchmarks.provider_artifacts import _io_path

from .offline_recovery import LOCKS, ROOT
from .prepare_live import LIVE_CASES


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str) and re.fullmatch(r"\s*[+-]?\d+(?:\.\d+)?\s*", value):
        return float(value)
    return None


def _measurement_value(item: dict) -> float | None:
    raw = _number(item.get("raw_value"))
    declared = _number(item.get("value"))
    if raw is None or declared is None or not math.isclose(raw, declared, rel_tol=0, abs_tol=1e-9):
        return None
    return raw


def _expected(gold: dict) -> list[dict]:
    points = []
    if gold["case_id"] == "BIO-GOLD-A":
        for variant in gold["variants"]:
            label = variant["label"]
            points.extend([
                {"sample": label, "property": "pore_size", "value": variant["measured_pore_size_um"], "unit": "um", "time": None},
                {"sample": label, "property": "volume_porosity", "value": variant["volume_porosity_percent"], "unit": "%", "time": None},
            ])
            for day, value in zip(gold["viability_times_day"], variant["viability_percent"]):
                points.append({"sample": label, "property": "cell_viability", "value": value, "unit": "%",
                               "time": f"day {day}", "cell_line": gold["cell_line"], "assay": gold["viability_assay"]})
            for day, value in zip(gold["proliferation_times_day"], variant["proliferation_ratio"]):
                points.append({"sample": label, "property": "cell_proliferation_ratio", "value": value, "unit": "1",
                               "time": f"day {day}", "cell_line": gold["cell_line"], "assay": gold["proliferation_assay"]})
    else:
        columns = [
            ("E. coli", "ATCC 25922", "undiluted"), ("E. coli", "ATCC 25922", "diluted_50_percent"),
            ("S. aureus", "ATCC 29213", "undiluted"), ("S. aureus", "ATCC 29213", "diluted_50_percent"),
            ("C. albicans", "ATCC 14053", "undiluted"), ("C. kruzei", "ATCC 6258", "undiluted"),
        ]
        for variant in gold["variants"]:
            for (organism, strain, dilution), value in zip(columns, variant["values"]):
                if value is not None:
                    points.append({"sample": variant["label"], "property": "inhibition_zone", "value": value,
                                   "unit": "mm", "organism": organism, "strain": strain, "dilution": dilution,
                                   "assay": gold["assay"]})
    if len(points) != gold["gold_output_count"]:
        raise ValueError("Frozen gold point count mismatch")
    return points


def _records(raw: dict) -> list[dict]:
    devices = {str(item.get("local_id")): item for item in raw.get("devices", []) if isinstance(item, dict)}
    records = []
    for experiment in raw.get("experiments", []):
        if not isinstance(experiment, dict):
            continue
        refs = experiment.get("device_refs") or []
        if not isinstance(refs, list):
            refs = [refs]
        linked = [devices[str(ref)] for ref in refs if str(ref) in devices]
        for output in experiment.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            conditions = output.get("conditions") if isinstance(output.get("conditions"), dict) else {}
            explicit_label = conditions.get("sample_label")
            linked_labels = [item.get("configuration", {}).get("sample_label") for item in linked
                             if isinstance(item.get("configuration"), dict)]
            sample = explicit_label or (linked_labels[0] if len(set(linked_labels)) == 1 and linked_labels else None)
            if explicit_label and linked_labels and any(_norm(explicit_label) != _norm(label) for label in linked_labels):
                sample = None
            records.append({"sample": sample, "output": output, "conditions": conditions,
                            "focal": experiment.get("ownership") == "focal_work" and bool(linked)
                                     and all(item.get("ownership") == "focal_work" for item in linked)})
    return records


def _context_matches(expected: dict, record: dict) -> bool:
    conditions = record["conditions"]
    for key in ("cell_line", "assay", "organism", "strain", "dilution"):
        if key in expected and _norm(conditions.get(key)) != _norm(expected[key]):
            return False
    if "time" in expected and _norm(conditions.get("exposure_time")) != _norm(expected["time"]):
        return False
    return True


def score_raw_case(raw: dict, gold: dict) -> dict:
    if gold["case_id"] not in LIVE_CASES:
        raise ValueError("Only approved A/B cases may be scientifically scored here")
    expected = _expected(gold)
    records = _records(raw)
    details = []
    for point in expected:
        candidates = [record for record in records
                      if _norm(record["sample"]) == _norm(point["sample"])
                      and record["output"].get("property") == point["property"]
                      and _context_matches(point, record)]
        exact = [record for record in candidates
                 if _norm(record["output"].get("unit")) == _norm(point["unit"])
                 and (value := _measurement_value(record["output"])) is not None
                 and math.isclose(value, point["value"], rel_tol=0, abs_tol=1e-9)]
        chosen = exact[0] if len(exact) == 1 else None
        evidence = chosen["output"].get("evidence") if chosen else None
        if isinstance(evidence, dict):
            evidence = [evidence]
        if not isinstance(evidence, list):
            evidence = []
        details.append({
            "expected": point, "candidate_count": len(candidates), "exact_candidate_count": len(exact),
            "exact_value_unit_context": chosen is not None,
            "page_evidence": any(isinstance(item, dict) and item.get("page") is not None for item in evidence),
            "table_evidence": any(isinstance(item, dict) and item.get("table_id") for item in evidence),
            "snippet_evidence": any(isinstance(item, dict) and item.get("text_snippet") for item in evidence),
            "direct_focal_ownership": bool(chosen and chosen["focal"]),
        })
    matched = [item for item in details if item["exact_value_unit_context"]]
    return {
        "case_id": gold["case_id"], "source": "original_raw_provider_payload_only",
        "expected_points": len(expected), "raw_output_count": len(records),
        "exact_value_unit_context_points": len(matched),
        "page_evidence_points": sum(bool(item["page_evidence"]) for item in matched),
        "table_evidence_points": sum(bool(item["table_evidence"]) for item in matched),
        "snippet_evidence_points": sum(bool(item["snippet_evidence"]) for item in matched),
        "direct_focal_ownership_points": sum(bool(item["direct_focal_ownership"]) for item in matched),
        "point_details": details, "canonical_admission_not_implied": True,
    }


def score_run(report_path: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    case_id = report["case_id"]
    if case_id not in LIVE_CASES:
        raise ValueError("Unapproved Biomaterials scoring case")
    lock = LOCKS[case_id]
    gold_path = ROOT / lock["gold"]
    if sha256(gold_path.read_bytes()).hexdigest() != lock["gold_sha256"]:
        raise ValueError("Frozen gold hash mismatch")
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    attempts = [item["attempt_number"] for item in report["attempts"] if item.get("payload_returned")]
    if not attempts:
        raise ValueError("No raw provider payload; scientific score must remain null")
    attempt_root = report_path.parent / f"attempt-{attempts[0]}"
    raw_path = _io_path(attempt_root / "raw_response.txt")
    digest_path = _io_path(attempt_root / "raw_response_sha256.json")
    digest = sha256(raw_path.read_bytes()).hexdigest()
    if digest != json.loads(digest_path.read_text(encoding="utf-8"))["sha256"]:
        raise ValueError("Immutable raw provider hash mismatch")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    if isinstance(raw, list) and len(raw) == 1:
        raw = raw[0]
    if not isinstance(raw, dict):
        raise ValueError("Raw response is not a scoreable document object")
    scientific = score_raw_case(raw, gold)
    scored = {
        "scoring_version": "biomaterials_raw_v1_conservative",
        "case_id": case_id, "model_id": report["model_id"], "run_id": report["run_id"],
        "raw_response_sha256": digest, "raw_scientific_score": scientific,
        "schema_valid": report["schema_valid"], "canonical_admission": report["canonical_admission"],
        "bio_live_gate_qualifying": scientific["exact_value_unit_context_points"] > 0,
        "original_report": str(report_path),
    }
    destination = report_path.parent / "scored_report_v1.json"
    with _io_path(destination).open("xb") as stream:
        stream.write((json.dumps(scored, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return scored


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    scored = score_run(args.report)
    print(json.dumps({"case_id": scored["case_id"], "model_id": scored["model_id"],
                      "exact": scored["raw_scientific_score"]["exact_value_unit_context_points"],
                      "expected": scored["raw_scientific_score"]["expected_points"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
