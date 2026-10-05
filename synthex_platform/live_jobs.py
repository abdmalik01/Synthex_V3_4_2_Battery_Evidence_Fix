"""Single-host durable coordinator for the normal uploaded-PDF extraction path."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import re
import threading
from types import SimpleNamespace
from typing import Any, Iterator
from uuid import uuid4

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.identifiers import stable_id
from synthex_platform.jobs import JobStore, classify_failure
from synthex_platform.providers.gemini_gateway import provider_attempt_observer
from synthex_platform.retrieval.serper_client import search_action_observer
from synthex_platform.source_store import SourceStore
from synthex_platform.storage import JsonlArchiveStore
from synthex_platform.storage.atomic_jsonl import _io_path
from synthex_platform.version import __version__


_process_locks: dict[str, threading.Lock] = {}
_process_locks_guard = threading.Lock()


class JobAlreadyRunning(RuntimeError):
    pass


@contextmanager
def execution_lock(root: Path, job_id: str) -> Iterator[None]:
    """Nonblocking process-and-thread lock; stale lock files are harmless."""
    if not isinstance(job_id, str) or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", job_id) is None or ".." in job_id:
        raise ValueError("unsafe job ID for execution lock")
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / f"{job_id}.lock"
    key = str(lock_path.resolve()).casefold()
    with _process_locks_guard:
        thread_lock = _process_locks.setdefault(key, threading.Lock())
    if not thread_lock.acquire(blocking=False):
        raise JobAlreadyRunning("job already has a local executor")
    fd = None
    locked = False
    try:
        fd = os.open(_io_path(lock_path), os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise JobAlreadyRunning("job already has a local executor") from exc
        yield
    finally:
        if locked and fd is not None:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        if fd is not None:
            os.close(fd)
        thread_lock.release()


class _ProviderObserver:
    def __init__(self, jobs: JobStore, sources: SourceStore, job_id: str):
        self.jobs, self.sources, self.job_id = jobs, sources, job_id

    def before(self, *, model: str, phase: str, contents: Any, config: Any) -> str:
        attempt_id = uuid4().hex
        request_hash = sha256((repr(contents) + repr(config)).encode("utf-8")).hexdigest()
        self.jobs.provider_intent(self.job_id, attempt_id=attempt_id, model=model,
                                  phase=phase, request_hash=request_hash)
        return attempt_id

    def succeeded(self, attempt_id: str, response: Any) -> None:
        raw = getattr(response, "text", None)
        if raw is None:
            raw = ""
        ref = self.sources.publish_artifact(str(raw).encode("utf-8"), category="raw")
        self.jobs.provider_outcome(self.job_id, attempt_id=attempt_id, raw_ref=ref)

    def failed(self, attempt_id: str, error: BaseException) -> None:
        self.jobs.provider_outcome(self.job_id, attempt_id=attempt_id,
                                   failure_class=classify_failure(error))


class OfflineReplayUnavailable(ValueError):
    pass


class _ReplayObserver:
    """Re-run deterministic parsing with exact stored responses, never a network call."""
    def __init__(self, sources: SourceStore, attempts: list[dict[str, Any]]):
        self.sources, self.attempts, self.index = sources, [a for a in attempts if a["status"] != "CONFIRMED_NO_RESULT"], 0

    def replay(self, *, model: str, phase: str, contents: Any, config: Any) -> Any:
        if self.index >= len(self.attempts):
            raise OfflineReplayUnavailable("no durable response for requested provider phase")
        attempt = self.attempts[self.index]
        expected_hash = sha256((repr(contents) + repr(config)).encode("utf-8")).hexdigest()
        if (attempt["model"], attempt["phase"], attempt["request_hash"]) != (model, phase, expected_hash):
            raise OfflineReplayUnavailable("provider replay request differs from durable attempt")
        if attempt["status"] != "RAW_PERSISTED" or not attempt.get("raw_ref"):
            raise OfflineReplayUnavailable("provider outcome is not replayable")
        self.index += 1
        return SimpleNamespace(text=self.sources.load_artifact(attempt["raw_ref"], category="raw").decode("utf-8"))


class _SearchObserver:
    """Job-scoped search action journal with ordered, checksum-verified replay."""
    def __init__(self, jobs: JobStore, sources: SourceStore, job_id: str,
                 actions: list[dict[str, Any]], *, allow_new: bool):
        self.jobs, self.sources, self.job_id = jobs, sources, job_id
        self.actions, self.index, self.allow_new = actions, 0, allow_new

    def replay(self, *, request_hash: str) -> tuple[bytes, bool | None] | None:
        while self.index < len(self.actions):
            action = self.actions[self.index]
            if action["request_hash"] != request_hash:
                raise OfflineReplayUnavailable("search query differs from durable action")
            self.index += 1
            if action["status"] == "CONFIRMED_NO_RESULT":
                continue
            if action["status"] != "RESULT_PERSISTED" or not action.get("response_artifact_id"):
                raise OfflineReplayUnavailable("search outcome is not safely replayable")
            return (self.sources.load_artifact(action["response_artifact_id"], category="search"),
                    action.get("cache_hit"))
        if not self.allow_new:
            raise OfflineReplayUnavailable("new search requires an explicit operator resume")
        return None

    def before(self, *, request_hash: str) -> str:
        if not self.allow_new:
            raise OfflineReplayUnavailable("new search requires an explicit operator resume")
        action_id = uuid4().hex
        self.jobs.external_intent(self.job_id, action_id=action_id, service="serper",
                                  operation="search", request_hash=request_hash)
        return action_id

    def succeeded(self, action_id: str, payload: bytes, *, cache_hit: bool) -> None:
        ref = self.sources.publish_artifact(payload, category="search")
        self.jobs.external_outcome(self.job_id, action_id=action_id, response_ref=ref,
                                   cache_hit=cache_hit)

    def failed(self, action_id: str, error: BaseException) -> None:
        self.jobs.external_outcome(self.job_id, action_id=action_id,
                                   failure_class=classify_failure(error))


class LiveExtractionService:
    def __init__(self, *, root: str | Path = "data/jobs", archive_store: JsonlArchiveStore | None = None):
        self.root = Path(root)
        self.sources = SourceStore(self.root)
        self.jobs = JobStore(self.root / "events.jsonl")
        self.archives = archive_store or JsonlArchiveStore("data/archive/archives.jsonl")

    def submit(self, pdf_bytes: bytes, *, filename: str, domain: str, pipeline: Any) -> str:
        source = self.sources.publish(pdf_bytes, filename=filename)
        job_id = f"job-{uuid4().hex}"
        model = pipeline.model or os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"
        fallbacks = tuple(pipeline.fallback_models) if pipeline.fallback_models is not None else tuple(
            value.strip() for value in os.getenv("GEMINI_FALLBACK_MODELS", "").split(",") if value.strip()
        )
        if any(re.fullmatch(r"(?:models/)?gemini-[A-Za-z0-9._-]{1,120}", value) is None
               for value in (model, *fallbacks)):
            raise ValueError("execution model must be an exact Gemini model ID")
        snapshot = {
            "domain": domain, "source_id": source["source_id"], "extractor_version": __version__,
            "schema_version": ArchiveMetadata.model_fields["schema_version"].default,
            "provider": "gemini", "model": model,
            "fallback_models": list(fallbacks), "provider_mode": pipeline.provider_mode,
            "search_assisted": bool(pipeline.search_assisted),
            "find_supplementary": bool(pipeline.find_supplementary),
            "enable_ocr": bool(pipeline.enable_ocr), "prompt_version": "repository-current",
        }
        self.jobs.create(job_id, run_id=f"run-{uuid4().hex}", task_type="extraction",
                         domain=domain, source_id=source["source_id"], provider="gemini",
                         model=model, source=source, execution=snapshot)
        return job_id

    def execute(self, job_id: str, *, pipeline: Any,
                permit_new_external_after_replay: bool = False) -> tuple[Any, SynthexArchive]:
        with execution_lock(self.root / "locks", job_id):
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job["state"] == "SUCCEEDED":
                archive = self.archives.get(job["artifacts"]["archive_id"])
                if archive is None:
                    raise ValueError("completed archive missing")
                return None, archive
            if job["state"] in {"FAILED", "CANCELLED", "RECONCILIATION_REQUIRED"}:
                raise ValueError("job requires operator review")
            job = self.jobs.reconcile_uncertain(job_id)
            if job["state"] == "RECONCILIATION_REQUIRED":
                raise ValueError("external action outcome uncertain; operator reconciliation required")
            if job["state"] == "ARCHIVING":
                archive = SynthexArchive.model_validate_json(self.sources.load_artifact(job["artifacts"]["validation"], category="validated"))
                return None, self._finish(job_id, archive)
            if job["state"] == "VALIDATING" and "validation" in job["artifacts"]:
                self.jobs.transition(job_id, "ARCHIVING")
                archive = SynthexArchive.model_validate_json(self.sources.load_artifact(job["artifacts"]["validation"], category="validated"))
                return None, self._finish(job_id, archive)
            replaying = job["state"] in {"WAITING_PROVIDER", "VALIDATING"} and "raw_response" in job["artifacts"]
            if job["state"] == "WAITING_PROVIDER" and not replaying and job["provider_attempts"] and job["provider_attempts"][-1]["status"] != "CONFIRMED_NO_RESULT":
                raise ValueError("provider outcome unavailable; operator review required")
            source_path = self.sources.load(job["source"])
            snapshot = job["execution"]
            if (snapshot.get("extractor_version") != __version__ or
                    snapshot.get("schema_version") != ArchiveMetadata.model_fields["schema_version"].default):
                raise OfflineReplayUnavailable("job was created under an incompatible extraction version")
            pipeline.model = snapshot["model"]
            pipeline.fallback_models = snapshot["fallback_models"]
            pipeline.provider_mode = snapshot["provider_mode"]
            pipeline.search_assisted = snapshot["search_assisted"]
            pipeline.find_supplementary = snapshot["find_supplementary"]
            pipeline.enable_ocr = snapshot["enable_ocr"]
            if replaying and getattr(pipeline, "api_key", None) is None:
                # Extractor constructors require a nonempty key even though the
                # replay observer intercepts every gateway call before the SDK.
                pipeline.api_key = "offline-replay-no-network"
            if job["state"] == "PENDING":
                job = self.jobs.transition(job_id, "RUNNING", artifacts={"source_locked": job["source"]["artifact_ref"]})
            try:
                bundle = pipeline.build_source_bundle(source_path, source_filename=job["source"]["filename"])
                if not replaying and job["state"] == "RUNNING":
                    self.jobs.transition(job_id, "WAITING_PROVIDER")
                observer = _ReplayObserver(self.sources, job["provider_attempts"]) if replaying else _ProviderObserver(self.jobs, self.sources, job_id)
                search_observer = _SearchObserver(self.jobs, self.sources, job_id,
                                                  job.get("external_actions", []),
                                                  allow_new=not replaying or permit_new_external_after_replay)
                observer_token = provider_attempt_observer.set(observer)
                search_token = search_action_observer.set(search_observer)
                try:
                    route, archive = pipeline.extract_source_bundle(bundle, domain=snapshot["domain"])
                finally:
                    provider_attempt_observer.reset(observer_token)
                    search_action_observer.reset(search_token)
                if replaying and observer.index != len(observer.attempts):
                    raise OfflineReplayUnavailable("not all durable provider attempts were replayed")
                if search_observer.index != len(search_observer.actions):
                    raise OfflineReplayUnavailable("not all durable search actions were replayed")
                original_archive_id = archive.metadata.archive_id
                archive.metadata.archive_id = stable_id("arc", original_archive_id, job_id)
                for relation in archive.relationships:
                    if relation.subject_id == original_archive_id:
                        relation.subject_id = archive.metadata.archive_id
                    if relation.object_id == original_archive_id:
                        relation.object_id = archive.metadata.archive_id
                    if relation.subject_id == archive.metadata.archive_id or relation.object_id == archive.metadata.archive_id:
                        relation.relation_id = stable_id("rel", relation.subject_id, relation.predicate, relation.object_id)
                archive = SynthexArchive.model_validate(archive.model_dump(mode="json"))
                if self.jobs.get(job_id)["state"] != "VALIDATING":
                    self.jobs.transition(job_id, "VALIDATING")
                ref = self.sources.publish_artifact(archive.model_dump_json(exclude_none=True).encode("utf-8"), category="validated")
                self.jobs.transition(job_id, "ARCHIVING", artifacts={"validation": ref})
                return route, self._finish(job_id, archive)
            except Exception as exc:
                current = self.jobs.get(job_id)
                if current and current["state"] in {"RUNNING", "WAITING_PROVIDER", "VALIDATING", "ARCHIVING"} and not isinstance(exc, OfflineReplayUnavailable):
                    attempts = current.get("provider_attempts", [])
                    external = current.get("external_actions", [])
                    if (not attempts or attempts[-1]["status"] != "TRANSMISSION_INTENT_RECORDED") and (
                        not external or external[-1]["status"] != "INTENT_RECORDED"
                    ):
                        self.jobs.record_failure(job_id, exc)
                    else:
                        self.jobs.reconcile_uncertain(job_id)
                raise

    def resume_safe(self, job_id: str, *, action_id: str, reason: str,
                    pipeline: Any) -> tuple[Any, SynthexArchive] | None:
        _, created = self.jobs.operator_action(job_id, action_id=action_id,
                                               decision="RESUME_SAFE", reason=reason)
        if not created:
            return None
        return self.execute(job_id, pipeline=pipeline, permit_new_external_after_replay=True)

    def reconcile(self, job_id: str, *, action_id: str, decision: str, reason: str,
                  external_action_id: str, expected_request_hash: str,
                  expected_source_id: str, expected_model: str | None = None,
                  artifact_ref: str | None = None) -> dict[str, Any]:
        with execution_lock(self.root / "locks", job_id):
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            already_recorded = any(action["action_id"] == action_id for action in job.get("operator_actions", []))
            if decision == "RESULT_RECOVERED" and not already_recorded:
                target = self.jobs._uncertain_action(job)
                if target is None:
                    raise ValueError("no uncertain action")
                category = "search" if target[0] == "search" else "raw"
                self.sources.load_artifact(artifact_ref or "", category=category)
            result, _ = self.jobs.operator_action(
                job_id, action_id=action_id, decision=decision, reason=reason,
                external_action_id=external_action_id, artifact_ref=artifact_ref,
                expected_request_hash=expected_request_hash,
                expected_model=expected_model, expected_source_id=expected_source_id,
            )
            return result

    def _finish(self, job_id: str, archive: SynthexArchive) -> SynthexArchive:
        self.jobs.complete_archive(job_id, archive, self.archives)
        return archive
