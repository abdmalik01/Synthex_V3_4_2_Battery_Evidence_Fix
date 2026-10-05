"""Verify immutable Gemini run artifacts and append the interim live gate."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from synthex_platform.benchmarks.provider_artifacts import _io_path

from .source_tables import ROOT, source_lock


OUTPUT = ROOT.parents[1] / "output/semiconductors_v1/provider_runs"
GATE = ROOT / "live_gate.json"
APPROVED_CASES = {"SEM-GOLD-A", "SEM-TRANSPORT-B"}


def build_live_gate() -> dict:
    runs = []
    for path in sorted(OUTPUT.glob("SEM-*/gemini/*/*/report.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        case_id = report["case_id"]
        if case_id not in APPROVED_CASES:
            raise ValueError(f"Unapproved case in Semiconductor live run tree: {case_id}")
        lock = source_lock(case_id)
        if report["source_hashes"] != {
            "article_sha256": lock["article_sha256"], "gold_sha256": lock["gold_sha256"]
        }:
            raise ValueError(f"Source/gold lock mismatch in live report: {path}")
        if report["fallback_used"] or len(report["attempts"]) > 3:
            raise ValueError(f"Uncontrolled Gemini run: {path}")
        manifest = json.loads((path.parent / "input_manifest.json").read_text(encoding="utf-8"))
        discovery = json.loads(Path(manifest["discovery_artifact"]).read_text(encoding="utf-8"))
        eligible = {item["model_id"] for item in discovery["eligible_general_text_models"]}
        if report["model_id"] not in eligible or manifest["model_id"] != report["model_id"]:
            raise ValueError(f"Model was not exact-discovery pinned: {path}")
        prompt = (path.parent / "request_prompt.txt").read_bytes()
        if sha256(prompt).hexdigest() != manifest["prompt_sha256"]:
            raise ValueError(f"Prompt digest mismatch: {path}")
        payload_numbers = [item["attempt_number"] for item in report["attempts"]
                           if item.get("payload_returned")]
        raw_hash = None
        score = None
        response = None
        if payload_numbers:
            attempt_root = path.parent / f"attempt-{payload_numbers[0]}"
            raw = _io_path(attempt_root / "raw_response.txt").read_bytes()
            raw_hash = sha256(raw).hexdigest()
            stored_hash = json.loads(_io_path(attempt_root / "raw_response_sha256.json").read_text(encoding="utf-8"))["sha256"]
            if raw_hash != stored_hash:
                raise ValueError(f"Raw response hash mismatch: {path}")
            scored_path = path.parent / "scored_report_v2.json"
            score = json.loads(scored_path.read_text(encoding="utf-8"))
            if score["raw_response_sha256"] != raw_hash or score["run_id"] != report["run_id"]:
                raise ValueError(f"Scored report/raw identity mismatch: {path}")
            response = json.loads(_io_path(attempt_root / "response_metadata.json").read_text(encoding="utf-8"))
            identity = response["identity"]
            if identity["model_id"] != report["model_id"] or identity["configured_model_id"] != report["model_id"]:
                raise ValueError(f"Provider response model identity mismatch: {path}")
        replay_path = path.parent / "repair_replay.json"
        repair_replay = json.loads(replay_path.read_text(encoding="utf-8")) if replay_path.exists() else None
        runs.append({
            "case_id": case_id, "model_id": report["model_id"], "run_id": report["run_id"],
            "status": report["status"], "attempts": report["attempts"],
            "payload_returned": bool(payload_numbers), "raw_response_sha256": raw_hash,
            "scoreable": bool(score and score["scientifically_scoreable"]),
            "raw_scientific_score": score["raw_scientific_score"] if score else None,
            "schema_valid": report["schema_valid"],
            "canonical_admission": report["canonical_admission"],
            "repair_attempted": report["repair_attempted"],
            "repair_replay": repair_replay,
            "latency_ms": response["latency_ms"] if response else None,
            "usage": response["usage"] if response else None,
            "artifact_run_root": path.parent.relative_to(ROOT.parents[1]).as_posix(),
        })
    qualifying = [item for item in runs if item["scoreable"]]
    models = {item["model_id"] for item in runs}
    if len(models) > 3:
        raise ValueError("More than three exact Gemini models in this interim benchmark")
    return {
        "schema": "synthex.semiconductors.live_gate.v1",
        "status": "INTERIM_LIVE_NOT_FROZEN",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "SEM_LIVE_GATE_SATISFIED": bool(qualifying),
        "qualification_rule": "at least one exact discovered Gemini model returns a persisted, hash-verified, scientifically scoreable raw payload for a locked Semiconductor case; canonical admission is not required",
        "provider_name": "gemini", "models_run": sorted(models),
        "run_count": len(runs), "qualifying_run_ids": [item["run_id"] for item in qualifying],
        "runs": runs,
        "limitations": [
            "First four offline cases remain interim, not a V1 freeze.",
            "Raw scientific recovery is separate from provider schema validity and canonical admission.",
            "SEM-TRANSPORT-B's original run status includes an audit-recorder long-path failure after the repair response; its append-only offline replay records the actual repaired schema result.",
        ],
    }


def main() -> int:
    gate = build_live_gate()
    with GATE.open("xb") as stream:
        stream.write((json.dumps(gate, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(json.dumps({
        "artifact": str(GATE), "SEM_LIVE_GATE_SATISFIED": gate["SEM_LIVE_GATE_SATISFIED"],
        "models_run": gate["models_run"], "run_count": gate["run_count"],
        "qualifying_run_ids": gate["qualifying_run_ids"],
    }, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
