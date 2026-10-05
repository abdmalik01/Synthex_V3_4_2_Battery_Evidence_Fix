import pytest
import json

from synthex_platform.jobs import JobStore, classify_failure
from synthex_platform.storage import JsonlArchiveStore
from tests_v3.test_platform import make_archive


def test_restart_after_each_checkpoint_and_no_automatic_provider_retry(tmp_path):
    path = tmp_path / "jobs.jsonl"
    jobs = JobStore(path)
    jobs.create("job-1", run_id="run-1", task_type="extraction", domain="batteries", source_id="source-1", provider="gemini", model="exact-model")
    assert JobStore(path).resume_plan("job-1")["action"] == "start"
    jobs.transition("job-1", "RUNNING", artifacts={"source_locked": "sha256:abc"})
    assert JobStore(path).resume_plan("job-1")["action"] == "resume_before_provider"
    jobs.transition("job-1", "WAITING_PROVIDER", attempt_delta=1)
    assert JobStore(path).resume_plan("job-1")["may_call_provider"] is False
    jobs.transition("job-1", "VALIDATING", artifacts={"raw_response": "artifact:raw-1"})
    assert JobStore(path).resume_plan("job-1")["action"] == "validate_raw_artifact"
    jobs.transition("job-1", "ARCHIVING", artifacts={"validation": "artifact:valid-1"})
    assert JobStore(path).resume_plan("job-1")["action"] == "finalize_archive"


def test_duplicate_finalization_after_archive_stage_is_idempotent(tmp_path):
    jobs = JobStore(tmp_path / "jobs.jsonl")
    archive = make_archive()
    store = JsonlArchiveStore(tmp_path / "archives.jsonl")
    jobs.create("job-1", run_id="run-1", task_type="extraction", domain="batteries", source_id="src")
    jobs.transition("job-1", "RUNNING")
    jobs.transition("job-1", "VALIDATING")
    jobs.transition("job-1", "ARCHIVING", artifacts={"validation": "artifact:v1"})
    store.append_unique(archive)  # simulate crash after archive fsync, before success event
    assert JobStore(tmp_path / "jobs.jsonl").complete_archive("job-1", archive, store)["state"] == "SUCCEEDED"
    assert jobs.complete_archive("job-1", archive, store)["state"] == "SUCCEEDED"
    assert store.count() == 1
    assert len(jobs.list_jobs()) == 1


def test_conflicting_archive_identity_cannot_append_second_record(tmp_path):
    jobs = JobStore(tmp_path / "jobs.jsonl")
    first = make_archive()
    second = make_archive()
    old_id = second.metadata.archive_id
    second.metadata.archive_id = old_id + "-other"
    for relation in second.relationships:
        if relation.subject_id == old_id:
            relation.subject_id = second.metadata.archive_id
        if relation.object_id == old_id:
            relation.object_id = second.metadata.archive_id
    store = JsonlArchiveStore(tmp_path / "archives.jsonl")
    jobs.create("job-1", run_id="run-1", task_type="extraction", domain="batteries", source_id="src")
    jobs.transition("job-1", "RUNNING")
    jobs.transition("job-1", "VALIDATING")
    jobs.transition("job-1", "ARCHIVING", artifacts={"validation": "artifact:v1"})
    jobs._bind_archive_identity("job-1", first.metadata.archive_id)
    with pytest.raises(ValueError, match="conflicting"):
        jobs.complete_archive("job-1", second, store)
    assert store.count() == 0
    assert jobs.complete_archive("job-1", first, store)["state"] == "SUCCEEDED"
    assert store.count() == 1


def test_illegal_transition_corrupt_record_and_failure_classification(tmp_path):
    path = tmp_path / "jobs.jsonl"
    jobs = JobStore(path)
    jobs.create("job-1", run_id="run-1", task_type="extraction", domain="batteries", source_id="src")
    with pytest.raises(ValueError, match="illegal"):
        jobs.transition("job-1", "SUCCEEDED")
    jobs.transition("job-1", "FAILED", error_class="provider_rate_limited")
    assert jobs.get("job-1")["error_class"] == "provider_rate_limited"
    assert classify_failure(TimeoutError("secret")) == "timeout"
    assert classify_failure(RuntimeError("HTTP 429")) == "provider_rate_limited"
    jobs.create("job-2", run_id="run-2", task_type="provider_extraction", domain="batteries", source_id="src")
    jobs.transition("job-2", "RUNNING")
    failed = jobs.record_failure("job-2", RuntimeError("HTTP 429 api_key=VERY_SECRET"))
    assert failed["error_class"] == "provider_rate_limited"
    assert "VERY_SECRET" not in path.read_text(encoding="utf-8")
    with path.open("ab") as stream:
        stream.write(b'{"job_id":')
    with pytest.raises(ValueError):
        JobStore(path).list_jobs()


def test_structurally_corrupt_but_valid_json_job_event_fails_closed(tmp_path):
    path = tmp_path / "jobs.jsonl"
    path.write_text(json.dumps({"job_id": "bad", "version": 1, "state": "PENDING"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt"):
        JobStore(path).list_jobs()


def test_malformed_provider_attempt_record_fails_closed(tmp_path):
    path = tmp_path / "jobs.jsonl"
    jobs = JobStore(path)
    jobs.create("job-1", run_id="run-1", task_type="extraction", domain="batteries", source_id="src")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["provider_attempts"] = ["invalid"]
    path.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt provider attempt"):
        JobStore(path).list_jobs()


def test_offline_resume_from_persisted_raw_artifact_without_provider_call(tmp_path):
    path = tmp_path / "jobs.jsonl"
    jobs = JobStore(path)
    archive = make_archive()
    archives = JsonlArchiveStore(tmp_path / "archives.jsonl")
    jobs.create("job-2", run_id="run-2", task_type="deterministic_extraction", domain="batteries", source_id="locked-source")
    jobs.transition("job-2", "RUNNING", artifacts={"source_locked": "sha256:abc"})
    jobs.transition("job-2", "VALIDATING", artifacts={"raw_response": "artifact:raw"})
    calls = {"load_raw": 0, "validate": 0, "save": 0, "load_validated": 0}
    artifacts = {}

    def load_raw(reference):
        calls["load_raw"] += 1
        assert reference == "artifact:raw"
        return "persisted local raw"

    def validate(raw):
        calls["validate"] += 1
        assert raw == "persisted local raw"
        return archive

    def save_validated(value):
        calls["save"] += 1
        artifacts["artifact:validated"] = value
        return "artifact:validated"

    def load_validated(reference):
        calls["load_validated"] += 1
        return artifacts[reference]

    kwargs = dict(load_raw=load_raw, validate_raw=validate, save_validated=save_validated, load_validated=load_validated, archive_store=archives)
    assert JobStore(path).resume_offline("job-2", **kwargs)["state"] == "SUCCEEDED"
    assert JobStore(path).resume_offline("job-2", **kwargs)["state"] == "SUCCEEDED"
    assert calls == {"load_raw": 1, "validate": 1, "save": 1, "load_validated": 1}
    assert archives.count() == 1
