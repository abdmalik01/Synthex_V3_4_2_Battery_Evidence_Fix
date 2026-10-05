"""Read-only, allowlisted projections of precomputed system-audit artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

from synthex_platform.jobs import JobStore
from synthex_platform.providers.contracts import redact_secrets


REPO_ROOT = Path(__file__).resolve().parents[1]
UNSTANDARDIZED = "not standardized"


def _safe_identifier(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 128:
        return None
    if value.startswith("/") or "\\" in value or ".." in value or ":" in value:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", value):
        return None
    return value


def _safe_artifact_ref(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"(?:sha256|artifact):[A-Za-z0-9._-]{1,100}", value):
        return value
    identifier = _safe_identifier(value)
    return identifier if identifier is not None and "/" not in identifier else None


def _safe_source(value: Any) -> str | None:
    source = _safe_identifier(value)
    if source is None or "/" in source and not source.startswith("10."):
        return None
    return source


def _safe_score(value: Any) -> int | float | dict[str, int | float] | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, dict):
        allowed = {
            "passed", "total", "raw_output_count", "raw_record_count", "outputs",
            "expected_points", "exact_value_and_unit_points", "exact_property_key_points",
            "exact_sample_count", "table_locator_points", "page_locator_points",
            "verbatim_snippet_points", "exact_point_recall", "value_accuracy",
            "coordinate_accuracy", "exact_matches", "expected_count", "recovered_count",
            "accuracy", "score", "percentage",
        }
        numeric = {
            key: number for key, number in value.items()
            if key in allowed and isinstance(number, (int, float)) and not isinstance(number, bool)
        }
        return numeric or None
    return None


def _metric(value: Any) -> int | str:
    return value if isinstance(value, int) and not isinstance(value, bool) else UNSTANDARDIZED


def _measurement(value: Any) -> int | str:
    if isinstance(value, list):
        return len(value)
    return _metric(value)


class SystemAuditReader:
    def __init__(self, root: str | Path | None = None, *, jobs: JobStore | None = None):
        self.root = Path(root) if root is not None else Path(os.getenv(
            "SYNTHEX_SYSTEM_AUDIT_ROOT", REPO_ROOT / "benchmark" / "system_audit"
        ))
        self.job_store = jobs or JobStore(Path(os.getenv(
            "SYNTHEX_JOB_LOG_PATH", REPO_ROOT / "data" / "jobs" / "events.jsonl"
        )))

    def _load(self, filename: str, key: str, expected_type: type) -> Any | None:
        try:
            value = json.loads((self.root / filename).read_text(encoding="utf-8"))
            item = value[key]
            return item if isinstance(item, expected_type) else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def status(self) -> dict[str, Any]:
        domains = self._load("domain_status.json", "domains", list)
        if domains is None:
            return {"status": "unavailable", "reason": "domain_audit_missing_or_invalid", "domains": []}
        projected = []
        for item in domains:
            if not isinstance(item, dict):
                continue
            name = _safe_identifier(item.get("domain"))
            if not name:
                continue
            pending = name == "biomaterials" and item.get("freeze_status") == "pending_live_provider_gate"
            projected.append({
                "domain": name,
                "scientific_status": _safe_identifier(item.get("scientific_status")) or UNSTANDARDIZED,
                "freeze_status": _safe_identifier(item.get("freeze_status")) or UNSTANDARDIZED,
                "display_status": "DETERMINISTICALLY CLOSED · LIVE GATE PENDING · NOT FROZEN" if pending else (
                    "FROZEN" if item.get("freeze_status") == "frozen" else "NOT FROZEN"
                ),
                "benchmark_case_count": _metric(item.get("benchmark_case_count")),
                "canonical_outputs": _metric(item.get("canonical_outputs")),
                "experiments": _metric(item.get("experiments")),
                "calculations": _metric(item.get("calculations")),
                "invariant_pass_count": _metric(item.get("invariant_pass_count")),
                "live_provider_gate": item.get("live_provider_gate") if isinstance(item.get("live_provider_gate"), bool) else UNSTANDARDIZED,
                "has_known_limitations": bool(item.get("known_limitations")),
            })
        worktree = self._load("worktree_audit.json", "entries", list)
        return {
            "status": "available", "domains": projected,
            "worktree": {"status": "available", "dirty_entry_count": len(worktree)} if worktree is not None else {"status": "unavailable"},
        }

    def benchmarks(self, domain: str | None = None) -> dict[str, Any]:
        cases = self._load("benchmark_registry.json", "cases", list)
        if cases is None:
            return {"status": "unavailable", "reason": "benchmark_audit_missing_or_invalid", "case_count": 0, "cases": []}
        projected = []
        statuses = {item["domain"]: item for item in self.status().get("domains", [])}
        for item in cases:
            if not isinstance(item, dict):
                continue
            name = _safe_identifier(item.get("domain"))
            if name is None or domain is not None and name != domain:
                continue
            hashes = item.get("source_hashes") if isinstance(item.get("source_hashes"), dict) else {}
            matches = item.get("hash_matches") if isinstance(item.get("hash_matches"), dict) else {}
            lock_integrity = (all(bool(matches.get(key)) for key in hashes) if hashes else None)
            source = item.get("source")
            projected.append({
                "domain": name, "case_id": _safe_identifier(item.get("case_id")),
                "source": _safe_source(source), "doi": _safe_identifier(item.get("doi")),
                "benchmark_type": _safe_identifier(item.get("benchmark_type")) or UNSTANDARDIZED,
                "output_count": _metric(item.get("deterministic_output_count")),
                "experiments": _metric(item.get("experiments")),
                "calculations": _metric(item.get("calculations")),
                "lock_integrity": lock_integrity if lock_integrity is not None else UNSTANDARDIZED,
                "closure_status": statuses.get(name, {}).get("scientific_status", UNSTANDARDIZED),
            })
        return {"status": "available", "case_count": len(projected), "cases": projected}

    def provider_runs(self, domain: str | None = None) -> dict[str, Any]:
        runs = self._load("provider_matrix.json", "runs", list)
        if runs is None:
            return {"status": "unavailable", "reason": "provider_audit_missing_or_invalid", "run_count": 0, "runs": []}
        projected = []
        for item in runs:
            if not isinstance(item, dict):
                continue
            name = _safe_identifier(item.get("domain"))
            if name is None or domain is not None and name != domain:
                continue
            payload = item.get("payload_returned") is True
            score = _safe_score(item.get("raw_scientific_score")) if payload else None
            errors = item.get("provider_error_classes") or []
            projected.append({
                "domain": name, "case_id": _safe_identifier(item.get("case")),
                "provider": _safe_identifier(item.get("provider")),
                "model": _safe_identifier(item.get("exact_model")),
                "run_id": _safe_identifier(item.get("run_id")),
                "payload": payload, "scientific_score": score if score is not None else "N/A",
                "schema_valid": item.get("schema_valid") if isinstance(item.get("schema_valid"), bool) else UNSTANDARDIZED,
                "normalization": _safe_identifier(item.get("normalization_status")) or UNSTANDARDIZED,
                "canonical_admission": item.get("canonical_admission") if isinstance(item.get("canonical_admission"), bool) else UNSTANDARDIZED,
                "error_status": [_safe_identifier(error) for error in errors if _safe_identifier(error)] if isinstance(errors, list) else [],
            })
        return {"status": "available", "run_count": len(projected), "runs": projected}

    def safety(self) -> dict[str, Any]:
        source = self._load("scientific_safety.json", "by_domain", dict)
        if source is None:
            return {"status": "unavailable", "reason": "safety_audit_missing_or_invalid", "domains": {}}
        aliases = {
            "ownership_contamination": ("ownership_contamination", "ownership"),
            "evidence_violations": ("evidence_violations", "evidence"),
            "cross_record_leakage": ("cross_record_leakage",),
            "analytics_contamination": ("analytics_contamination", "archive_analytics", "analytics"),
            "graph_contamination": ("graph_contamination", "graph"),
        }
        domains = {}
        for name, item in source.items():
            safe_name = _safe_identifier(name)
            if safe_name is None or not isinstance(item, dict):
                continue
            reported = item.get("reported") if isinstance(item.get("reported"), dict) else {}
            domains[safe_name] = {
                **{dimension: _measurement(next((reported[key] for key in keys if key in reported), None)) for dimension, keys in aliases.items()},
                "basis_kind": _safe_identifier(item.get("basis_kind")) or UNSTANDARDIZED,
            }
        return {"status": "available", "domains": domains}

    def jobs(self) -> dict[str, Any]:
        try:
            jobs = self.job_store.list_jobs()
        except (OSError, ValueError):
            return {"status": "unavailable", "reason": "job_journal_invalid", "jobs": []}
        return {"status": "available", "jobs": [self._project_job(job) for job in jobs]}

    def job(self, job_id: str) -> dict[str, Any] | None:
        try:
            job = self.job_store.get(job_id)
        except (OSError, ValueError):
            return None
        return self._project_job(job) if job is not None else None

    @staticmethod
    def _project_job(job: dict[str, Any]) -> dict[str, Any]:
        error_class = _safe_identifier(job.get("error_class"))
        state = _safe_identifier(job.get("state"))
        source = job.get("source") if isinstance(job.get("source"), dict) else {}
        raw_filename = source.get("filename")
        filename = raw_filename if isinstance(raw_filename, str) and len(raw_filename) <= 255 and raw_filename == Path(raw_filename.replace("\\", "/")).name and not re.search(r"[\x00-\x1f]", raw_filename) else None
        attempts = job.get("provider_attempts") if isinstance(job.get("provider_attempts"), list) else []
        external = job.get("external_actions") if isinstance(job.get("external_actions"), list) else []
        target = JobStore._uncertain_action(job)
        uncertain = state == "RECONCILIATION_REQUIRED" or bool(state == "WAITING_PROVIDER" and target)
        projection = {
            key: _safe_identifier(job.get(key))
            for key in ("job_id", "run_id", "state", "domain", "task_type", "source_id", "provider", "model", "error_class")
        } | {
            "created_at": job.get("created_at"), "updated_at": job.get("updated_at"),
            "attempt_count": job.get("attempt_count"),
            "error_summary": error_class.replace("_", " ") if error_class else None,
            "stage": state.replace("_", " ").title() if state else None,
            "source_filename": re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", redact_secrets(filename)) if filename else None,
            "source_sha256_prefix": source.get("sha256", "")[:12] if isinstance(source.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", source["sha256"]) else None,
            "reconciliation_required": uncertain,
            "status_reason": "External action outcome is uncertain; operator reconciliation required. No automatic retry." if uncertain else (error_class.replace("_", " ") if error_class else None),
            "artifact_refs": {key: _safe_artifact_ref(value) for key, value in job.get("artifacts", {}).items() if _safe_identifier(key) and _safe_artifact_ref(value)},
            "safe_to_resume": JobStore.safe_to_resume(job),
            "reconciliation_target": ({"action_type": target[0],
                                       "action_id": _safe_identifier(target[1].get("action_id") or target[1].get("attempt_id")),
                                       "request_hash": _safe_identifier(target[1].get("request_hash")),
                                       "model": _safe_identifier(target[1].get("model"))} if target else None),
            "external_action_count": len(external),
            "operator_action_count": len(job.get("operator_actions", [])),
        }
        projection["source_id"] = _safe_source(job.get("source_id"))
        return projection
