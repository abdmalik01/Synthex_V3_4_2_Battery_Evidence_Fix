"""Offline, fail-closed scoring of independently reviewed MECH-GOLD-A assertions.

This module never extracts a paper or calls a provider. A source lock and human-reviewed
assertions are prerequisites; the shipped contract deliberately has neither.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.visual.analytics.projection import project_archives


def score_archive(archive: SynthexArchive, contract: dict[str, Any]) -> dict[str, Any]:
    source = contract.get("source") or {}
    assertions = contract.get("assertions") or []
    if contract.get("status") != "locked_reviewed" or not source.get("sha256") or not assertions:
        raise ValueError("MECH-GOLD-A requires a locked source and independently reviewed assertions")
    if archive.metadata.domain != "mechanical":
        raise ValueError("MECH-GOLD-A requires a Mechanical archive")
    if any(not all(key in item for key in (
        "property", "value", "unit", "sample", "conditions", "scientific_type", "evidence_text"
    )) for item in assertions):
        raise ValueError("Every gold assertion needs value, unit, sample, conditions, type, and evidence")

    rows = project_archives([archive])
    matched: list[dict[str, Any]] = []
    for assertion in assertions:
        property_rows = [row for row in rows if (
            row.modality == "experimental"
            and row.property_name == assertion["property"]
        )]
        value_rows = [row for row in property_rows if (
            row.value is not None
            and abs(row.value - assertion["value"]) <= max(1e-9, abs(assertion["value"]) * 1e-6)
            and (row.normalized_unit or row.unit) == assertion["unit"]
        )]
        association_rows = [row for row in value_rows if (
            row.material_label == assertion["sample"]
            and all(row.conditions.get(key) == value for key, value in assertion["conditions"].items())
        )]
        type_rows = [row for row in association_rows if row.conditions.get("scientific_type") == assertion["scientific_type"]]
        evidence_rows = [row for row in type_rows if (
            any(assertion["evidence_text"] in str(ref.get("text_snippet") or "") for ref in row.evidence_references)
        )]
        matched.append({
            "property": assertion["property"], "sample": assertion["sample"],
            "property_found": bool(property_rows), "value_unit_correct": bool(value_rows),
            "association_correct": bool(association_rows), "scientific_type_correct": bool(type_rows),
            "source_tracked": bool(evidence_rows), "passed": bool(evidence_rows),
        })
    passed = sum(item["passed"] for item in matched)
    quarantine = [item for payload in archive.domain_payloads for item in payload.values.get("admissibility", {}).get("quarantined_objects", [])]
    quarantine_checks = []
    for expected in contract.get("quarantine_assertions", []):
        found = any(
            item.get("property") == expected.get("property")
            and item.get("reason") == expected.get("reason")
            and item.get("raw_object", {}).get("raw_value") == expected.get("raw_value")
            for item in quarantine
        )
        quarantine_checks.append({**expected, "passed": found})
    return {
        "case_id": contract["case_id"], "passed": passed, "total": len(assertions),
        "recall": passed / len(assertions), "assertions": matched,
        "routing_correct": archive.metadata.domain == "mechanical",
        "admitted_rows": len(rows), "quarantined_objects": len(quarantine),
        "quarantine_assertions": quarantine_checks,
    }


def score_files(archive_path: str | Path, contract_path: str | Path, source_path: str | Path) -> dict[str, Any]:
    archive = SynthexArchive.model_validate_json(Path(archive_path).read_text(encoding="utf-8"))
    contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
    source = contract.get("source") or {}
    path = Path(source_path)
    if path.name != source.get("filename") or sha256(path.read_bytes()).hexdigest() != source.get("sha256"):
        raise ValueError("MECH-GOLD-A source file does not match its lock")
    if source.get("title") and (not archive.sources or archive.sources[0].title != source["title"]):
        raise ValueError("MECH-GOLD-A archive title does not match its source lock")
    return score_archive(archive, contract)
