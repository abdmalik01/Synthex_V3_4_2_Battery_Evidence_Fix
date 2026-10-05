"""Durable local job event journal; resume decisions never invoke a provider."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Callable

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.storage import JsonlArchiveStore
from synthex_platform.storage.atomic_jsonl import JsonlLog


ACTIVE = {"PENDING", "RUNNING", "WAITING_PROVIDER", "VALIDATING", "ARCHIVING"}
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "RECONCILIATION_REQUIRED"}
ERROR_CLASSES = {
    "provider_transient_unavailable", "provider_rate_limited", "provider_authentication",
    "provider_invalid_request", "timeout", "schema_invalid",
    "scientific_admission_failure", "archive_failure", "storage_failure",
    "unknown_internal_failure",
}
OPERATOR_REASONS = {"operator_requested", "operator_verified", "operator_uncertain", "operator_abandoned"}
TRANSITIONS = {
    "PENDING": {"RUNNING", "FAILED", "CANCELLED"},
    "RUNNING": {"WAITING_PROVIDER", "VALIDATING", "FAILED", "CANCELLED"},
    "WAITING_PROVIDER": {"VALIDATING", "FAILED", "CANCELLED", "RECONCILIATION_REQUIRED"},
    "VALIDATING": {"ARCHIVING", "FAILED", "CANCELLED"},
    "ARCHIVING": {"SUCCEEDED", "FAILED", "CANCELLED"},
    "SUCCEEDED": set(), "FAILED": set(), "CANCELLED": set(),
    "RECONCILIATION_REQUIRED": {"PENDING", "WAITING_PROVIDER", "VALIDATING", "CANCELLED"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_logical_id(value: Any) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= 128
        and not value.startswith("/") and ".." not in value
        and re.fullmatch(r"[A-Za-z0-9._/-]+", value) is not None
    )


def _is_artifact_ref(value: Any) -> bool:
    return (isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value) is not None) or (
        isinstance(value, str)
        and re.fullmatch(r"(?:sha256|artifact):[A-Za-z0-9._-]{1,100}", value) is not None
    )


def classify_failure(exc: BaseException) -> str:
    """Conservative normalized class only; never persist raw exception text."""
    name = type(exc).__name__.casefold()
    message = str(exc).casefold()
    if isinstance(exc, TimeoutError) or "timeout" in name:
        return "timeout"
    if "429" in message or "rate" in name and "limit" in name:
        return "provider_rate_limited"
    if "auth" in name or "401" in message or "403" in message:
        return "provider_authentication"
    if "invalidrequest" in name or "400" in message:
        return "provider_invalid_request"
    if "unavailable" in name or "503" in message:
        return "provider_transient_unavailable"
    if "schema" in name or "validation" in name:
        return "schema_invalid"
    if "admission" in name or "scientific" in name:
        return "scientific_admission_failure"
    if "archive" in name:
        return "archive_failure"
    if isinstance(exc, OSError):
        return "storage_failure"
    return "unknown_internal_failure"


class JobStore:
    def __init__(self, path: str | Path):
        self.log = JsonlLog(path)

    @staticmethod
    def _fold(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        current: dict[str, dict[str, Any]] = {}
        required = {
            "job_id", "run_id", "version", "state", "task_type", "domain",
            "source_id", "provider", "model", "created_at", "updated_at",
            "attempt_count", "artifacts", "error_class",
        }
        for event in rows:
            if not required <= event.keys() or not isinstance(event.get("artifacts"), dict):
                raise ValueError("corrupt job-state record")
            if "source" in event and event["source"] is not None and not isinstance(event["source"], dict):
                raise ValueError("corrupt durable source record")
            if "execution" in event and event["execution"] is not None and not isinstance(event["execution"], dict):
                raise ValueError("corrupt execution snapshot")
            if "provider_attempts" in event and (not isinstance(event["provider_attempts"], list) or any(
                not isinstance(attempt, dict) or attempt.get("status") not in {
                    "TRANSMISSION_INTENT_RECORDED", "RAW_PERSISTED", "FAILED_RECORDED", "CONFIRMED_NO_RESULT"
                } for attempt in event["provider_attempts"]
            )):
                raise ValueError("corrupt provider attempt record")
            if not isinstance(event.get("external_actions", []), list) or any(
                not isinstance(action, dict) or action.get("status") not in {
                    "INTENT_RECORDED", "RESULT_PERSISTED", "FAILED_CONFIRMED", "CONFIRMED_NO_RESULT"
                } for action in event.get("external_actions", [])
            ) or not isinstance(event.get("operator_actions", []), list):
                raise ValueError("corrupt external/operator action record")
            identifier = event.get("job_id")
            version = event.get("version")
            state = event.get("state")
            if not isinstance(identifier, str) or not identifier or state not in TRANSITIONS or not isinstance(event.get("attempt_count"), int):
                raise ValueError("corrupt job-state record")
            previous = current.get(identifier)
            if previous is None:
                if version != 1 or state != "PENDING":
                    raise ValueError("corrupt job-state creation record")
            elif version != previous["version"] + 1:
                raise ValueError("corrupt job-state transition record")
            elif state == "ARCHIVING" and previous["state"] == "ARCHIVING":
                before = previous["artifacts"]
                after = event["artifacts"]
                if "archive_id" in before or not _is_artifact_ref(after.get("archive_id")) or after != {**before, "archive_id": after["archive_id"]}:
                    raise ValueError("corrupt archive identity binding")
            elif state == previous["state"] and len(event.get("operator_actions", [])) == len(previous.get("operator_actions", [])) + 1:
                if event["operator_actions"][:-1] != previous.get("operator_actions", []):
                    raise ValueError("corrupt operator action history")
            elif state == "WAITING_PROVIDER" and previous["state"] == "WAITING_PROVIDER":
                before = previous.get("provider_attempts", [])
                after = event.get("provider_attempts", [])
                new_intent = (
                    len(after) == len(before) + 1 and after[:-1] == before
                    and after[-1]["status"] == "TRANSMISSION_INTENT_RECORDED"
                    and event["attempt_count"] == previous["attempt_count"] + 1
                )
                recorded_outcome = (
                    bool(before) and len(after) == len(before) and after[:-1] == before[:-1]
                    and before[-1]["status"] == "TRANSMISSION_INTENT_RECORDED"
                    and after[-1]["attempt_id"] == before[-1]["attempt_id"]
                    and after[-1]["status"] in {"RAW_PERSISTED", "FAILED_RECORDED"}
                    and event["attempt_count"] == previous["attempt_count"]
                )
                before_external = previous.get("external_actions", [])
                after_external = event.get("external_actions", [])
                new_external = (len(after_external) == len(before_external) + 1
                                and after_external[:-1] == before_external
                                and after_external[-1]["status"] == "INTENT_RECORDED")
                external_outcome = (bool(before_external) and len(after_external) == len(before_external)
                                    and after_external[:-1] == before_external[:-1]
                                    and before_external[-1]["status"] == "INTENT_RECORDED"
                                    and after_external[-1]["action_id"] == before_external[-1]["action_id"]
                                    and after_external[-1]["status"] in {"RESULT_PERSISTED", "FAILED_CONFIRMED"})
                if not (new_intent or recorded_outcome or new_external or external_outcome):
                    raise ValueError("corrupt external attempt record")
                if (new_external or external_outcome) and (after != before or event["attempt_count"] != previous["attempt_count"]):
                    raise ValueError("external action changed provider attempt")
            elif previous["state"] == "RECONCILIATION_REQUIRED":
                before_actions = previous.get("operator_actions", [])
                after_actions = event.get("operator_actions", [])
                if (state not in TRANSITIONS[previous["state"]] | {"RECONCILIATION_REQUIRED"}
                        or len(after_actions) != len(before_actions) + 1
                        or after_actions[:-1] != before_actions):
                    raise ValueError("reconciliation requires one operator action")
            elif state not in TRANSITIONS[previous["state"]]:
                raise ValueError("corrupt job-state transition record")
            current[identifier] = event
        return current

    def create(
        self, job_id: str, *, run_id: str, task_type: str, domain: str,
        source_id: str, provider: str | None = None, model: str | None = None,
        source: dict[str, Any] | None = None, execution: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not all(_is_logical_id(value) for value in (job_id, run_id, task_type, domain, source_id)) or "/" in source_id and not source_id.startswith("10."):
            raise ValueError("job identity fields must be safe logical IDs")
        if provider is not None and not _is_logical_id(provider) or model is not None and not _is_logical_id(model):
            raise ValueError("provider and model must be safe logical IDs")
        if source is not None:
            if source.get("source_id") != source_id or not _is_artifact_ref(source.get("artifact_ref")):
                raise ValueError("invalid durable source metadata")
        if execution is not None:
            if not isinstance(execution, dict) or execution.get("domain") != domain or execution.get("source_id") != source_id:
                raise ValueError("invalid execution snapshot")
            if any("key" in key.casefold() or "secret" in key.casefold() or "token" in key.casefold() for key in execution):
                raise ValueError("execution snapshot contains secret-bearing field")
        result: dict[str, Any] = {}

        def build(rows):
            current = self._fold(rows)
            if job_id in current:
                old = current[job_id]
                if any(old[key] != value for key, value in {
                    "run_id": run_id, "task_type": task_type, "domain": domain,
                    "source_id": source_id, "provider": provider, "model": model,
                    "source": source, "execution": execution,
                }.items()):
                    raise ValueError("conflicting job_id")
                result.update(old)
                return None
            created = _now()
            event = {
                "job_id": job_id, "run_id": run_id, "version": 1,
                "task_type": task_type, "domain": domain, "source_id": source_id,
                "provider": provider, "model": model, "created_at": created,
                "updated_at": created, "state": "PENDING", "attempt_count": 0,
                "artifacts": {}, "error_class": None,
                "source": source, "execution": execution, "provider_attempts": [],
                "external_actions": [], "operator_actions": [],
            }
            result.update(event)
            return event

        self.log.transact(build)
        return result

    def transition(
        self, job_id: str, state: str, *, artifacts: dict[str, str] | None = None,
        attempt_delta: int = 0, error_class: str | None = None,
    ) -> dict[str, Any]:
        if state not in TRANSITIONS:
            raise ValueError(f"unknown job state: {state}")
        if attempt_delta < 0 or not isinstance(attempt_delta, int):
            raise ValueError("attempt_delta must be nonnegative")
        if artifacts is not None and (not isinstance(artifacts, dict) or not all(
            _is_logical_id(key) and _is_artifact_ref(value)
            for key, value in artifacts.items()
        )):
            raise ValueError("artifact references must be logical IDs, not filesystem paths")
        if error_class is not None and error_class not in ERROR_CLASSES:
            raise ValueError("error_class must be a normalized class")
        result: dict[str, Any] = {}

        def build(rows):
            old = self._fold(rows).get(job_id)
            if old is None:
                raise KeyError(job_id)
            merged = {**old["artifacts"], **(artifacts or {})}
            if state == old["state"] and merged == old["artifacts"] and attempt_delta == 0 and error_class == old.get("error_class"):
                result.update(old)
                return None
            if state not in TRANSITIONS[old["state"]]:
                raise ValueError(f"illegal job transition: {old['state']} -> {state}")
            if state == "SUCCEEDED" and "archive_id" not in merged:
                raise ValueError("successful job requires archived record identity")
            if state == "FAILED" and not error_class:
                raise ValueError("failed job requires normalized error_class")
            event = {
                **old, "version": old["version"] + 1, "state": state,
                "updated_at": _now(), "attempt_count": old["attempt_count"] + attempt_delta,
                "artifacts": merged, "error_class": error_class,
            }
            result.update(event)
            return event

        self.log.transact(build)
        return result

    def record_failure(self, job_id: str, exc: BaseException) -> dict[str, Any]:
        """Record only a normalized class, never raw provider or exception text."""
        return self.transition(job_id, "FAILED", error_class=classify_failure(exc))

    def provider_intent(self, job_id: str, *, attempt_id: str, model: str, phase: str, request_hash: str) -> dict[str, Any]:
        """Durably record uncertainty before handing a request to the SDK."""
        if not all(_is_artifact_ref(value) for value in (attempt_id, phase, request_hash)) or not _is_logical_id(model):
            raise ValueError("unsafe provider attempt metadata")
        result: dict[str, Any] = {}

        def build(rows):
            old = self._fold(rows).get(job_id)
            if old is None or old["state"] != "WAITING_PROVIDER":
                raise ValueError("provider intent requires WAITING_PROVIDER")
            attempt = {
                "attempt_id": attempt_id, "job_id": job_id, "run_id": old["run_id"],
                "provider": old["provider"], "model": model, "phase": phase,
                "attempt_number": old["attempt_count"] + 1, "request_hash": request_hash,
                "source_artifact_ref": (old.get("source") or {}).get("artifact_ref"),
                "status": "TRANSMISSION_INTENT_RECORDED", "intended_at": _now(),
            }
            event = {**old, "version": old["version"] + 1, "updated_at": _now(),
                     "attempt_count": old["attempt_count"] + 1,
                     "provider_attempts": [*old.get("provider_attempts", []), attempt]}
            result.update(event)
            return event

        self.log.transact(build)
        return result

    def provider_outcome(self, job_id: str, *, attempt_id: str, raw_ref: str | None = None,
                         failure_class: str | None = None) -> dict[str, Any]:
        if raw_ref is not None and not _is_artifact_ref(raw_ref):
            raise ValueError("invalid raw artifact reference")
        if failure_class is not None and failure_class not in ERROR_CLASSES:
            raise ValueError("invalid failure class")
        if (raw_ref is None) == (failure_class is None):
            raise ValueError("exactly one outcome required")
        result: dict[str, Any] = {}

        def build(rows):
            old = self._fold(rows).get(job_id)
            if old is None or old["state"] != "WAITING_PROVIDER":
                raise ValueError("provider outcome requires WAITING_PROVIDER")
            attempts = list(old.get("provider_attempts", []))
            if not attempts or attempts[-1]["attempt_id"] != attempt_id or attempts[-1]["status"] != "TRANSMISSION_INTENT_RECORDED":
                raise ValueError("provider outcome has no matching intent")
            attempts[-1] = {**attempts[-1], "status": "RAW_PERSISTED" if raw_ref else "FAILED_RECORDED",
                            "outcome_at": _now(), "raw_ref": raw_ref, "failure_class": failure_class}
            artifacts = {**old["artifacts"]}
            if raw_ref:
                artifacts["raw_response"] = raw_ref
            event = {**old, "version": old["version"] + 1, "updated_at": _now(),
                     "provider_attempts": attempts, "artifacts": artifacts}
            result.update(event)
            return event

        self.log.transact(build)
        return result

    def reconcile_uncertain(self, job_id: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        def build(rows):
            old = self._fold(rows).get(job_id)
            if old is None:
                raise KeyError(job_id)
            if old["state"] != "WAITING_PROVIDER" or self._uncertain_action(old) is None:
                result.update(old)
                return None
            event = {**old, "version": old["version"] + 1,
                     "state": "RECONCILIATION_REQUIRED", "updated_at": _now()}
            result.update(event)
            return event
        self.log.transact(build)
        return result

    def external_intent(self, job_id: str, *, action_id: str, service: str,
                        operation: str, request_hash: str) -> dict[str, Any]:
        if not all(_is_artifact_ref(value) for value in (action_id, service, operation, request_hash)):
            raise ValueError("unsafe external action metadata")
        result: dict[str, Any] = {}
        def build(rows):
            old = self._fold(rows).get(job_id)
            if old is None or old["state"] != "WAITING_PROVIDER":
                raise ValueError("external intent requires WAITING_PROVIDER")
            actions = old.get("external_actions", [])
            if any(item["action_id"] == action_id for item in actions):
                raise ValueError("duplicate external action ID")
            action = {"action_id": action_id, "job_id": job_id, "run_id": old["run_id"],
                      "source_id": old["source_id"], "action_type": operation, "service": service,
                      "operation": operation, "attempt": len(actions) + 1,
                      "request_hash": request_hash, "status": "INTENT_RECORDED",
                      "intent_recorded_at": _now(), "started_at": _now()}
            event = {**old, "version": old["version"] + 1, "updated_at": _now(),
                     "external_actions": [*actions, action]}
            result.update(event)
            return event
        self.log.transact(build)
        return result

    def external_outcome(self, job_id: str, *, action_id: str, response_ref: str | None = None,
                         failure_class: str | None = None,
                         cache_hit: bool | None = None) -> dict[str, Any]:
        if (response_ref is None) == (failure_class is None):
            raise ValueError("exactly one external outcome required")
        if response_ref is not None and not _is_artifact_ref(response_ref):
            raise ValueError("invalid response artifact")
        if failure_class is not None and failure_class not in ERROR_CLASSES:
            raise ValueError("invalid failure class")
        if cache_hit is not None and (not isinstance(cache_hit, bool) or response_ref is None):
            raise ValueError("invalid search cache provenance")
        result: dict[str, Any] = {}
        def build(rows):
            old = self._fold(rows).get(job_id)
            if old is None or old["state"] != "WAITING_PROVIDER":
                raise ValueError("external outcome requires WAITING_PROVIDER")
            actions = list(old.get("external_actions", []))
            if not actions or actions[-1]["action_id"] != action_id or actions[-1]["status"] != "INTENT_RECORDED":
                raise ValueError("external outcome has no matching intent")
            actions[-1] = {**actions[-1], "status": "RESULT_PERSISTED" if response_ref else "FAILED_CONFIRMED",
                           "response_artifact_id": response_ref, "error_class": failure_class,
                           "cache_hit": cache_hit, "completed_at": _now()}
            event = {**old, "version": old["version"] + 1, "updated_at": _now(), "external_actions": actions}
            result.update(event)
            return event
        self.log.transact(build)
        return result

    def operator_action(self, job_id: str, *, action_id: str, decision: str,
                        reason: str, external_action_id: str | None = None,
                        artifact_ref: str | None = None, expected_request_hash: str | None = None,
                        expected_model: str | None = None, expected_source_id: str | None = None) -> tuple[dict[str, Any], bool]:
        """Append one local operator decision; never performs external I/O.

        A repeated action ID with identical arguments is a no-op. Reuse with
        different arguments is rejected, including after the state has moved.
        """
        allowed = {"RESUME_SAFE", "OUTCOME_UNKNOWN", "CONFIRMED_NO_RESULT", "RESULT_RECOVERED", "ABANDON"}
        if (decision not in allowed or not isinstance(action_id, str)
                or re.fullmatch(r"[0-9a-f]{32}", action_id) is None
                or reason not in OPERATOR_REASONS):
            raise ValueError("invalid operator decision metadata")
        if external_action_id is not None and not _is_artifact_ref(external_action_id):
            raise ValueError("invalid external action ID")
        if artifact_ref is not None and not _is_artifact_ref(artifact_ref):
            raise ValueError("invalid artifact reference")
        inputs = {"decision": decision, "reason": reason, "external_action_id": external_action_id,
                  "artifact_ref": artifact_ref, "expected_request_hash": expected_request_hash,
                  "expected_model": expected_model, "expected_source_id": expected_source_id}
        result: dict[str, Any] = {}
        created = False
        def build(rows):
            nonlocal created
            old = self._fold(rows).get(job_id)
            if old is None:
                raise KeyError(job_id)
            prior = next((a for a in old.get("operator_actions", []) if a["action_id"] == action_id), None)
            if prior is not None:
                if prior["inputs"] != inputs:
                    raise ValueError("conflicting operator action ID")
                result.update(old)
                return None
            state = old["state"]
            if decision == "RESUME_SAFE":
                if not self.safe_to_resume(old):
                    raise ValueError("job is not safe to resume")
                new_state = state
            else:
                if state != "RECONCILIATION_REQUIRED":
                    raise ValueError("reconciliation decision requires RECONCILIATION_REQUIRED")
                target = self._uncertain_action(old)
                if target is None or target[1]["action_id" if target[0] == "search" else "attempt_id"] != external_action_id:
                    raise ValueError("reconciliation target does not match uncertain action")
                kind, pending = target
                if (expected_request_hash != pending["request_hash"] or
                        expected_source_id != old["source_id"] or
                        (kind == "provider" and expected_model != pending["model"]) or
                        (kind == "search" and expected_model is not None)):
                    raise ValueError("reconciliation request/model/source identity mismatch")
                if decision == "RESULT_RECOVERED" and not artifact_ref:
                    raise ValueError("recovered result requires persisted artifact")
                if decision != "RESULT_RECOVERED" and artifact_ref is not None:
                    raise ValueError("artifact supplied for non-recovery decision")
                if (decision == "CONFIRMED_NO_RESULT" and kind == "provider"
                        and len(old["provider_attempts"]) != 1):
                    raise ValueError("multi-phase provider attempt cannot restart from source safely")
                new_state = {"OUTCOME_UNKNOWN": state, "CONFIRMED_NO_RESULT": "PENDING" if kind == "provider" else "WAITING_PROVIDER",
                             "RESULT_RECOVERED": "VALIDATING" if kind == "provider" else "WAITING_PROVIDER",
                             "ABANDON": "CANCELLED"}[decision]
            at = _now()
            audit = {"job_id": job_id, "action_id": action_id, "action_type": decision,
                     "timestamp": at, "prior_state": state, "resulting_state": new_state,
                     "reason_category": reason, "artifact_ref": artifact_ref,
                     "operator_id": "local_operator", "inputs": inputs}
            event = {**old, "version": old["version"] + 1, "updated_at": at,
                     "state": new_state, "operator_actions": [*old.get("operator_actions", []), audit]}
            if decision in {"CONFIRMED_NO_RESULT", "RESULT_RECOVERED"}:
                if kind == "provider":
                    attempts = list(old["provider_attempts"])
                    attempts[-1] = {**pending, "status": "CONFIRMED_NO_RESULT" if decision == "CONFIRMED_NO_RESULT" else "RAW_PERSISTED",
                                    "raw_ref": artifact_ref, "outcome_at": at}
                    event["provider_attempts"] = attempts
                    if artifact_ref:
                        event["artifacts"] = {**old["artifacts"], "raw_response": artifact_ref}
                else:
                    actions = list(old["external_actions"])
                    actions[-1] = {**pending, "status": "CONFIRMED_NO_RESULT" if decision == "CONFIRMED_NO_RESULT" else "RESULT_PERSISTED",
                                   "response_artifact_id": artifact_ref, "completed_at": at}
                    event["external_actions"] = actions
            result.update(event)
            created = True
            return event
        self.log.transact(build)
        return result, created

    @staticmethod
    def _uncertain_action(job: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        external = job.get("external_actions", [])
        if external and external[-1]["status"] == "INTENT_RECORDED":
            return "search", external[-1]
        attempts = job.get("provider_attempts", [])
        if attempts and attempts[-1]["status"] == "TRANSMISSION_INTENT_RECORDED":
            return "provider", attempts[-1]
        return None

    @staticmethod
    def safe_to_resume(job: dict[str, Any]) -> bool:
        state = job["state"]
        if state not in ACTIVE or JobStore._uncertain_action(job):
            return False
        artifacts = job.get("artifacts", {})
        attempts = job.get("provider_attempts", [])
        external = job.get("external_actions", [])
        if state == "WAITING_PROVIDER":
            if external and external[-1]["status"] == "FAILED_CONFIRMED":
                return False
            return not attempts or bool(artifacts.get("raw_response")) or attempts[-1]["status"] == "CONFIRMED_NO_RESULT"
        if state == "VALIDATING":
            return bool(artifacts.get("raw_response") or artifacts.get("validation"))
        if state == "ARCHIVING":
            return bool(artifacts.get("validation"))
        return True

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self._fold(self.log.read_all()).get(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        return sorted(self._fold(self.log.read_all()).values(), key=lambda item: item["created_at"], reverse=True)

    def resume_plan(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        state = job["state"]
        artifacts = job["artifacts"]
        if state == "PENDING":
            action = "start"
        elif state == "RUNNING":
            action = "resume_before_provider"
        elif state == "WAITING_PROVIDER":
            attempts = job.get("provider_attempts", [])
            action = "reconcile_external" if self._uncertain_action(job) else "validate_raw_artifact" if "raw_response" in artifacts else (
                "resume_before_provider" if not attempts or attempts[-1]["status"] == "CONFIRMED_NO_RESULT" else "manual_provider_reconciliation"
            )
        elif state == "VALIDATING":
            action = "finalize_archive" if "validation" in artifacts else "validate_raw_artifact"
        elif state == "ARCHIVING":
            action = "finalize_archive"
        else:
            action = "done" if state == "SUCCEEDED" else "manual_review"
        return {"job_id": job_id, "state": state, "action": action,
                "safe_to_resume": self.safe_to_resume(job),
                "may_call_provider": False}

    def complete_archive(self, job_id: str, archive: SynthexArchive, store: JsonlArchiveStore) -> dict[str, Any]:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["state"] == "SUCCEEDED":
            if job["artifacts"].get("archive_id") != archive.metadata.archive_id:
                raise ValueError("conflicting completed archive identity")
            return job
        if job["state"] != "ARCHIVING":
            raise ValueError("illegal archive finalization state")
        self._bind_archive_identity(job_id, archive.metadata.archive_id)
        store.append_unique(archive)
        return self.transition(job_id, "SUCCEEDED", artifacts={"archive_id": archive.metadata.archive_id})

    def _bind_archive_identity(self, job_id: str, archive_id: str) -> dict[str, Any]:
        """Claim the one archive identity before any cross-file append occurs."""
        if not _is_artifact_ref(archive_id):
            raise ValueError("archive_id must be a safe stable identifier")
        result: dict[str, Any] = {}

        def build(rows):
            old = self._fold(rows).get(job_id)
            if old is None:
                raise KeyError(job_id)
            existing = old["artifacts"].get("archive_id")
            if existing is not None:
                if existing != archive_id:
                    raise ValueError("conflicting completed archive identity")
                result.update(old)
                return None
            if old["state"] != "ARCHIVING":
                raise ValueError("illegal archive identity binding state")
            event = {
                **old, "version": old["version"] + 1, "updated_at": _now(),
                "artifacts": {**old["artifacts"], "archive_id": archive_id},
            }
            result.update(event)
            return event

        self.log.transact(build)
        return result

    def resume_offline(
        self, job_id: str, *, load_raw: Callable[[str], Any],
        validate_raw: Callable[[Any], SynthexArchive],
        save_validated: Callable[[SynthexArchive], str],
        load_validated: Callable[[str], SynthexArchive],
        archive_store: JsonlArchiveStore,
    ) -> dict[str, Any]:
        """Replay only local persisted artifacts; no provider callback is accepted.

        ``save_validated`` must durably publish an immutable archive artifact and
        return its logical ID before the ARCHIVING transition is committed.
        """
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["state"] == "SUCCEEDED":
            return job
        if job["state"] in {"RUNNING", "WAITING_PROVIDER"} and "raw_response" in job["artifacts"]:
            job = self.transition(job_id, "VALIDATING")
        if job["state"] == "VALIDATING" and "validation" not in job["artifacts"]:
            raw_ref = job["artifacts"].get("raw_response")
            if not raw_ref:
                return self.resume_plan(job_id)
            archive = validate_raw(load_raw(raw_ref))
            validated_ref = save_validated(archive)
            job = self.transition(job_id, "ARCHIVING", artifacts={"validation": validated_ref})
        elif job["state"] == "VALIDATING" and "validation" in job["artifacts"]:
            job = self.transition(job_id, "ARCHIVING")
        if job["state"] == "ARCHIVING":
            archive = load_validated(job["artifacts"]["validation"])
            return self.complete_archive(job_id, archive, archive_store)
        return self.resume_plan(job_id)
