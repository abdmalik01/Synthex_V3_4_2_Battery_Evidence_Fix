"""Crash boundaries use fake provider responses; no external inference is possible."""

from types import SimpleNamespace
from hashlib import sha256
from concurrent.futures import ProcessPoolExecutor

import pytest

from synthex_platform.live_jobs import JobAlreadyRunning, LiveExtractionService, execution_lock
from synthex_platform.providers.gemini_gateway import GeminiGateway
from synthex_platform.source_store import SourceIntegrityError, SourceStore
from synthex_platform.storage import JsonlArchiveStore
from synthex_platform.system_status import SystemAuditReader
from tests_v3.test_platform import make_archive


PDF = b"%PDF-1.4\nmock source"


class _FakePipeline:
    def __init__(self, *, network_allowed=True):
        self.model = "models/gemini-test"
        self.fallback_models = []
        self.provider_mode = "production"
        self.search_assisted = False
        self.find_supplementary = False
        self.enable_ocr = False
        self.network_allowed = network_allowed
        self.calls = 0

    def build_source_bundle(self, path, *, source_filename):
        assert path.read_bytes() == PDF
        return SimpleNamespace(filename=source_filename)

    def extract_source_bundle(self, bundle, *, domain):
        pipeline = self

        class Models:
            def generate_content(self, **kwargs):
                pipeline.calls += 1
                if not pipeline.network_allowed:
                    raise AssertionError("network call during offline replay")
                return SimpleNamespace(text="persisted fake response")

        gateway = GeminiGateway(client=SimpleNamespace(models=Models()),
                                preferred_model=self.model, fallback_models=self.fallback_models)
        response = gateway.generate_primary(contents="prompt:" + bundle.filename, config={"temperature": 0})
        assert response.text == "persisted fake response"
        return SimpleNamespace(domain=domain), make_archive()


def _service(tmp_path):
    return LiveExtractionService(root=tmp_path / "jobs", archive_store=JsonlArchiveStore(tmp_path / "archives.jsonl"))


def _try_process_lock(root):
    try:
        with execution_lock(root, "job-1"):
            return True
    except JobAlreadyRunning:
        return False


def test_source_publication_identity_dedup_and_corruption(tmp_path, monkeypatch):
    sources = SourceStore(tmp_path)
    first = sources.publish(PDF, filename="first.pdf")
    second = sources.publish(PDF, filename="second.pdf")
    assert first["sha256"] == second["sha256"]
    assert first["source_id"] == second["source_id"]
    assert first["filename"] != second["filename"]
    assert len(list((tmp_path / "sources").glob("*.pdf"))) == 1
    assert sources.load(first).read_bytes() == PDF
    bad = {**first, "sha256": "0" * 64}
    with pytest.raises(FileNotFoundError):
        sources.load(bad)
    path = sources.load(first)
    path.write_bytes(b"%PDF-corrupted")
    with pytest.raises(SourceIntegrityError):
        sources.load(first)


def test_interrupted_source_publication_never_creates_job(tmp_path, monkeypatch):
    from synthex_platform import source_store
    service = _service(tmp_path)
    def interrupted(*args, **kwargs):
        raise OSError("simulated interruption")
    monkeypatch.setattr(source_store.os, "link", interrupted)
    with pytest.raises(OSError):
        service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=_FakePipeline())
    assert service.jobs.list_jobs() == []
    assert not list((tmp_path / "jobs" / "sources").glob("*.pdf"))
    assert not list((tmp_path / "jobs" / "sources").glob(".publish-*"))


def test_live_request_snapshot_archive_and_distinct_jobs(tmp_path):
    service = _service(tmp_path)
    pipeline = _FakePipeline()
    first = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=pipeline)
    second = service.submit(PDF, filename="paper.pdf", domain="catalysis", pipeline=pipeline)
    assert first != second
    assert service.jobs.get(first)["state"] == "PENDING"
    assert service.jobs.get(first)["source"]["artifact_ref"] == service.jobs.get(second)["source"]["artifact_ref"]
    pipeline.model = "models/gemini-changed"
    route, archive = service.execute(first, pipeline=pipeline)
    assert route.domain == "batteries"
    assert pipeline.model == "models/gemini-test"
    assert service.jobs.get(first)["state"] == "SUCCEEDED"
    assert service.jobs.get(first)["attempt_count"] == 1
    assert service.archives.get(archive.metadata.archive_id) is not None
    assert service.execute(first, pipeline=pipeline)[1].metadata.archive_id == archive.metadata.archive_id
    assert pipeline.calls == 1


def test_intent_without_outcome_requires_reconciliation(tmp_path):
    service = _service(tmp_path)
    pipeline = _FakePipeline(network_allowed=False)
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=pipeline)
    service.jobs.transition(job_id, "RUNNING")
    service.jobs.transition(job_id, "WAITING_PROVIDER")
    service.jobs.provider_intent(job_id, attempt_id="attempt-1", model=pipeline.model,
                                 phase="primary", request_hash="a" * 64)
    with pytest.raises(ValueError, match="reconciliation"):
        service.execute(job_id, pipeline=pipeline)
    assert service.jobs.get(job_id)["state"] == "RECONCILIATION_REQUIRED"
    assert pipeline.calls == 0
    projected = SystemAuditReader(jobs=service.jobs).job(job_id)
    assert projected["reconciliation_required"] is True
    assert "automatic retry" in projected["status_reason"]


def test_raw_response_offline_replay_no_second_provider_call(tmp_path, monkeypatch):
    service = _service(tmp_path)
    pipeline = _FakePipeline()
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=pipeline)
    original = service.jobs.transition
    def crash_before_validation(jid, state, **kwargs):
        if state == "VALIDATING":
            raise KeyboardInterrupt("simulated process death")
        return original(jid, state, **kwargs)
    monkeypatch.setattr(service.jobs, "transition", crash_before_validation)
    with pytest.raises(KeyboardInterrupt):
        service.execute(job_id, pipeline=pipeline)
    assert service.jobs.get(job_id)["state"] == "WAITING_PROVIDER"
    assert service.jobs.get(job_id)["provider_attempts"][0]["status"] == "RAW_PERSISTED"
    monkeypatch.setattr(service.jobs, "transition", original)
    replay = _FakePipeline(network_allowed=False)
    service.execute(job_id, pipeline=replay)
    assert replay.calls == 0
    assert service.jobs.get(job_id)["state"] == "SUCCEEDED"


def test_pending_and_running_resume_and_failed_no_retry(tmp_path):
    service = _service(tmp_path)
    pipeline = _FakePipeline()
    pending = service.submit(PDF, filename="a.pdf", domain="batteries", pipeline=pipeline)
    service.execute(pending, pipeline=pipeline)
    running = service.submit(PDF, filename="b.pdf", domain="batteries", pipeline=pipeline)
    service.jobs.transition(running, "RUNNING")
    service.execute(running, pipeline=pipeline)
    failed = service.submit(PDF, filename="c.pdf", domain="batteries", pipeline=pipeline)
    service.jobs.transition(failed, "FAILED", error_class="schema_invalid")
    with pytest.raises(ValueError, match="operator review"):
        service.execute(failed, pipeline=pipeline)


def test_competing_executor_and_stale_lock_file(tmp_path):
    root = tmp_path / "locks"
    with pytest.raises(ValueError, match="unsafe job ID"):
        with execution_lock(root, "../escape"):
            pass
    with execution_lock(root, "job-1"):
        with pytest.raises(JobAlreadyRunning):
            with execution_lock(root, "job-1"):
                pass
        with ProcessPoolExecutor(max_workers=1) as pool:
            assert pool.submit(_try_process_lock, root).result(timeout=15) is False
    # The sidecar remains after release, but the OS lock does not.
    assert (root / "job-1.lock").exists()
    with execution_lock(root, "job-1"):
        pass
    with ProcessPoolExecutor(max_workers=1) as pool:
        assert pool.submit(_try_process_lock, root).result(timeout=15) is True


def test_crash_before_provider_intent_can_resume(tmp_path):
    service = _service(tmp_path)
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=_FakePipeline())
    class CrashBeforeSend(_FakePipeline):
        def extract_source_bundle(self, bundle, *, domain):
            raise KeyboardInterrupt("process stopped before gateway send")
    with pytest.raises(KeyboardInterrupt):
        service.execute(job_id, pipeline=CrashBeforeSend())
    assert service.jobs.get(job_id)["state"] == "WAITING_PROVIDER"
    assert service.jobs.get(job_id)["provider_attempts"] == []
    replay = _FakePipeline()
    service.execute(job_id, pipeline=replay)
    assert replay.calls == 1
    assert service.jobs.get(job_id)["state"] == "SUCCEEDED"


def test_crash_after_validation_and_during_archive_append(tmp_path, monkeypatch):
    service = _service(tmp_path)
    first = service.submit(PDF, filename="a.pdf", domain="batteries", pipeline=_FakePipeline())
    original_finish = service._finish
    def crash_before_archive(*args):
        raise KeyboardInterrupt("crash after validated artifact")
    monkeypatch.setattr(service, "_finish", crash_before_archive)
    with pytest.raises(KeyboardInterrupt):
        service.execute(first, pipeline=_FakePipeline())
    assert service.jobs.get(first)["state"] == "ARCHIVING"
    monkeypatch.setattr(service, "_finish", original_finish)
    replay = _FakePipeline(network_allowed=False)
    service.execute(first, pipeline=replay)
    assert replay.calls == 0

    second = service.submit(PDF, filename="b.pdf", domain="batteries", pipeline=_FakePipeline())
    original_append = service.archives.append_unique
    def crash_after_append(archive):
        original_append(archive)
        raise KeyboardInterrupt("crash after archive fsync")
    monkeypatch.setattr(service.archives, "append_unique", crash_after_append)
    with pytest.raises(KeyboardInterrupt):
        service.execute(second, pipeline=_FakePipeline())
    assert service.jobs.get(second)["state"] == "ARCHIVING"
    monkeypatch.setattr(service.archives, "append_unique", original_append)
    service.execute(second, pipeline=_FakePipeline(network_allowed=False))
    assert service.jobs.get(second)["state"] == "SUCCEEDED"
    assert service.archives.count() == 2


def test_read_model_never_exposes_source_path_or_raw_text(tmp_path):
    service = _service(tmp_path)
    job_id = service.submit(PDF, filename="C:\\private\\paper.pdf", domain="batteries", pipeline=_FakePipeline())
    service.execute(job_id, pipeline=_FakePipeline())
    projected = SystemAuditReader(jobs=service.jobs).job(job_id)
    serialized = str(projected)
    assert "C:\\private" not in serialized
    assert "persisted fake response" not in serialized
    assert projected["source_filename"] == "paper.pdf"


def test_resume_fails_closed_on_corrupt_source_and_hash_mismatch(tmp_path):
    service = _service(tmp_path)
    pipeline = _FakePipeline(network_allowed=False)
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=pipeline)
    source = service.jobs.get(job_id)["source"]
    path = service.sources.load(source)
    path.write_bytes(b"%PDF-1.4\ntampered")
    with pytest.raises(SourceIntegrityError):
        service.execute(job_id, pipeline=pipeline)
    assert service.jobs.get(job_id)["state"] == "PENDING"
    assert pipeline.calls == 0


def test_search_assisted_raw_replay_fails_closed_before_new_search(tmp_path):
    service = _service(tmp_path)
    class _SearchPipeline(_FakePipeline):
        def extract_source_bundle(self, bundle, *, domain):
            from synthex_platform.retrieval.serper_client import SerperClient
            result = super().extract_source_bundle(bundle, domain=domain)
            SerperClient(api_key="fake", cache_dir=tmp_path / "search_cache").search("paper metadata")
            return result
    pipeline = _SearchPipeline(network_allowed=False)
    pipeline.search_assisted = True
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=pipeline)
    service.jobs.transition(job_id, "RUNNING")
    service.jobs.transition(job_id, "WAITING_PROVIDER")
    request_hash = sha256((repr("prompt:paper.pdf") + repr({"temperature": 0})).encode()).hexdigest()
    service.jobs.provider_intent(job_id, attempt_id="attempt-1", model=pipeline.model,
                                 phase="primary", request_hash=request_hash)
    raw_ref = service.sources.publish_artifact(b"persisted fake response", category="raw")
    service.jobs.provider_outcome(job_id, attempt_id="attempt-1", raw_ref=raw_ref)
    with pytest.raises(ValueError, match="new search requires"):
        service.execute(job_id, pipeline=pipeline)
    assert pipeline.calls == 0
