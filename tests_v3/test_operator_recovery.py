"""Operator and Serper crash boundaries; all network calls are local mocks."""

from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from synthex_platform import api
from synthex_platform.live_jobs import LiveExtractionService
from synthex_platform.retrieval.serper_client import SerperClient
from synthex_platform.storage import JsonlArchiveStore
from synthex_platform.system_status import SystemAuditReader
from tests_v3.test_live_jobs import PDF, _FakePipeline

ACTION_1 = "1" * 32
ACTION_2 = "2" * 32
RESUME_1 = "a" * 32


def _service(tmp_path):
    return LiveExtractionService(root=tmp_path / "jobs", archive_store=JsonlArchiveStore(tmp_path / "archives.jsonl"))


def _provider_hash():
    return sha256((repr("prompt:paper.pdf") + repr({"temperature": 0})).encode()).hexdigest()


def _provider_intent(service, job_id):
    service.jobs.transition(job_id, "RUNNING")
    service.jobs.transition(job_id, "WAITING_PROVIDER")
    service.jobs.provider_intent(job_id, attempt_id="attempt-1", model="models/gemini-test",
                                 phase="primary", request_hash=_provider_hash())


def _reconcile_args(service, job_id, *, decision, action_id=ACTION_1, artifact_ref=None):
    job = service.jobs.get(job_id)
    kind, target = service.jobs._uncertain_action(job)
    return dict(action_id=action_id, decision=decision, reason="operator_verified",
                external_action_id=target["attempt_id" if kind == "provider" else "action_id"],
                expected_request_hash=target["request_hash"], expected_source_id=job["source_id"],
                expected_model=target["model"] if kind == "provider" else None,
                artifact_ref=artifact_ref)


class SearchPipeline(_FakePipeline):
    def __init__(self, cache_dir, *, query="paper metadata", network_allowed=True):
        super().__init__(network_allowed=network_allowed)
        self.search_assisted = True
        self.cache_dir = cache_dir
        self.query = query

    def extract_source_bundle(self, bundle, *, domain):
        route, archive = super().extract_source_bundle(bundle, domain=domain)
        SerperClient(api_key="fake", cache_dir=self.cache_dir).search(self.query)
        return route, archive


def _fake_http(counter, *, body=b'{"organic": []}', error=False):
    def post(*args, **kwargs):
        counter.append(kwargs["json"])
        response = SimpleNamespace(content=body)
        if error:
            def fail():
                raise requests.HTTPError("429")
            response.raise_for_status = fail
        else:
            response.raise_for_status = lambda: None
        return response
    return post


def test_provider_reconciliation_idempotency_and_explicit_new_attempt(tmp_path):
    service = _service(tmp_path)
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=_FakePipeline())
    _provider_intent(service, job_id)
    service.jobs.reconcile_uncertain(job_id)
    args = _reconcile_args(service, job_id, decision="OUTCOME_UNKNOWN")
    service.reconcile(job_id, **args)
    version = service.jobs.get(job_id)["version"]
    service.reconcile(job_id, **args)
    assert service.jobs.get(job_id)["version"] == version
    with pytest.raises(ValueError, match="conflicting"):
        service.reconcile(job_id, **{**args, "reason": "operator_uncertain"})
    assert service.jobs.get(job_id)["state"] == "RECONCILIATION_REQUIRED"
    service.reconcile(job_id, **{**args, "action_id": ACTION_2, "decision": "CONFIRMED_NO_RESULT"})
    assert service.jobs.get(job_id)["state"] == "PENDING"
    assert service.jobs.get(job_id)["provider_attempts"][-1]["status"] == "CONFIRMED_NO_RESULT"
    assert service.jobs.get(job_id)["attempt_count"] == 1
    assert len(service.jobs.get(job_id)["operator_actions"]) == 2
    pipeline = _FakePipeline()
    service.resume_safe(job_id, action_id=RESUME_1, reason="operator_requested", pipeline=pipeline)
    assert pipeline.calls == 1
    assert service.jobs.get(job_id)["attempt_count"] == 2
    assert service.jobs.get(job_id)["state"] == "SUCCEEDED"
    assert service.resume_safe(job_id, action_id=RESUME_1, reason="operator_requested", pipeline=pipeline) is None
    assert pipeline.calls == 1


def test_recovered_provider_result_identity_and_no_network(tmp_path):
    service = _service(tmp_path)
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=_FakePipeline())
    _provider_intent(service, job_id)
    service.jobs.reconcile_uncertain(job_id)
    ref = service.sources.publish_artifact(b"persisted fake response", category="raw")
    args = _reconcile_args(service, job_id, decision="RESULT_RECOVERED", artifact_ref=ref)
    with pytest.raises(ValueError, match="identity mismatch"):
        service.reconcile(job_id, **{**args, "expected_request_hash": "b" * 64})
    with pytest.raises(FileNotFoundError):
        service.reconcile(job_id, **{**args, "artifact_ref": "sha256:" + "0" * 64})
    service.reconcile(job_id, **args)
    assert service.jobs.get(job_id)["state"] == "VALIDATING"
    version = service.jobs.get(job_id)["version"]
    service.reconcile(job_id, **args)
    assert service.jobs.get(job_id)["version"] == version
    replay = _FakePipeline(network_allowed=False)
    service.resume_safe(job_id, action_id=RESUME_1, reason="operator_requested", pipeline=replay)
    assert replay.calls == 0
    assert service.jobs.get(job_id)["state"] == "SUCCEEDED"


def test_confirmed_no_result_cannot_repeat_earlier_provider_phase(tmp_path):
    service = _service(tmp_path)
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=_FakePipeline())
    _provider_intent(service, job_id)
    ref = service.sources.publish_artifact(b"first phase", category="raw")
    service.jobs.provider_outcome(job_id, attempt_id="attempt-1", raw_ref=ref)
    service.jobs.provider_intent(job_id, attempt_id="attempt-2", model="models/gemini-test",
                                 phase="repair", request_hash="c" * 64)
    service.jobs.reconcile_uncertain(job_id)
    with pytest.raises(ValueError, match="multi-phase"):
        service.reconcile(job_id, **_reconcile_args(service, job_id, decision="CONFIRMED_NO_RESULT"))
    assert service.jobs.get(job_id)["state"] == "RECONCILIATION_REQUIRED"
    assert service.jobs.get(job_id)["attempt_count"] == 2


def test_abandon_is_terminal_and_journaled(tmp_path):
    service = _service(tmp_path)
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=_FakePipeline())
    _provider_intent(service, job_id)
    service.jobs.reconcile_uncertain(job_id)
    service.reconcile(job_id, **_reconcile_args(service, job_id, decision="ABANDON"))
    assert service.jobs.get(job_id)["state"] == "CANCELLED"
    assert service.jobs.get(job_id)["operator_actions"][-1]["action_type"] == "ABANDON"
    with pytest.raises(ValueError, match="not safe"):
        service.resume_safe(job_id, action_id=RESUME_1, reason="operator_requested", pipeline=_FakePipeline())


def test_search_intent_crash_requires_reconciliation_and_no_retry(tmp_path, monkeypatch):
    service = _service(tmp_path)
    pipeline = SearchPipeline(tmp_path / "cache")
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=pipeline)
    calls = []
    def crash(*args, **kwargs):
        calls.append(1)
        raise KeyboardInterrupt("crash after search intent")
    monkeypatch.setattr("synthex_platform.retrieval.serper_client.requests.post", crash)
    with pytest.raises(KeyboardInterrupt):
        service.execute(job_id, pipeline=pipeline)
    action = service.jobs.get(job_id)["external_actions"][0]
    assert action["status"] == "INTENT_RECORDED"
    assert action["source_id"] == service.jobs.get(job_id)["source_id"]
    assert len(calls) == 1
    with pytest.raises(ValueError, match="reconciliation"):
        service.execute(job_id, pipeline=SearchPipeline(tmp_path / "cache", network_allowed=False))
    assert len(calls) == 1
    assert service.jobs.get(job_id)["state"] == "RECONCILIATION_REQUIRED"
    service.reconcile(job_id, **_reconcile_args(service, job_id, decision="OUTCOME_UNKNOWN"))
    assert service.jobs.get(job_id)["state"] == "RECONCILIATION_REQUIRED"


def test_search_result_crash_replays_provider_and_search_locally(tmp_path, monkeypatch):
    service = _service(tmp_path)
    pipeline = SearchPipeline(tmp_path / "cache")
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=pipeline)
    calls = []
    monkeypatch.setattr("synthex_platform.retrieval.serper_client.requests.post", _fake_http(calls))
    original = service.jobs.transition
    def crash_before_validation(jid, state, **kwargs):
        if state == "VALIDATING":
            raise KeyboardInterrupt("crash after persisted search")
        return original(jid, state, **kwargs)
    monkeypatch.setattr(service.jobs, "transition", crash_before_validation)
    with pytest.raises(KeyboardInterrupt):
        service.execute(job_id, pipeline=pipeline)
    monkeypatch.setattr(service.jobs, "transition", original)
    assert len(calls) == 1
    action = service.jobs.get(job_id)["external_actions"][0]
    assert action["status"] == "RESULT_PERSISTED"
    assert action["cache_hit"] is False
    assert json.loads(service.sources.load_artifact(action["response_artifact_id"], category="search")) == {"organic": []}
    monkeypatch.setattr("synthex_platform.retrieval.serper_client.requests.post", lambda *a, **k: pytest.fail("unexpected search network"))
    replay = SearchPipeline(tmp_path / "other-cache", network_allowed=False)
    service.execute(job_id, pipeline=replay)
    assert replay.calls == 0
    assert service.jobs.get(job_id)["state"] == "SUCCEEDED"
    assert service.execute(job_id, pipeline=replay)[1].metadata.archive_id


def test_search_result_then_provider_checkpoint_does_not_repeat_search(tmp_path, monkeypatch):
    class SearchFirstPipeline(SearchPipeline):
        def extract_source_bundle(self, bundle, *, domain):
            SerperClient(api_key="fake", cache_dir=self.cache_dir).search(self.query)
            return _FakePipeline.extract_source_bundle(self, bundle, domain=domain)

    service = _service(tmp_path)
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries",
                            pipeline=SearchFirstPipeline(tmp_path / "cache"))
    calls = []
    monkeypatch.setattr("synthex_platform.retrieval.serper_client.requests.post", _fake_http(calls))
    class CrashBeforeProvider(SearchFirstPipeline):
        def extract_source_bundle(self, bundle, *, domain):
            SerperClient(api_key="fake", cache_dir=self.cache_dir).search(self.query)
            raise KeyboardInterrupt("after search, before provider")
    with pytest.raises(KeyboardInterrupt):
        service.execute(job_id, pipeline=CrashBeforeProvider(tmp_path / "cache"))
    assert len(calls) == 1
    assert service.jobs.get(job_id)["provider_attempts"] == []
    monkeypatch.setattr("synthex_platform.retrieval.serper_client.requests.post", lambda *a, **k: pytest.fail("search repeated"))
    service.execute(job_id, pipeline=SearchFirstPipeline(tmp_path / "different-cache"))
    assert service.jobs.get(job_id)["state"] == "SUCCEEDED"


def test_recovered_search_artifact_and_query_hash_guard(tmp_path, monkeypatch):
    service = _service(tmp_path)
    pipeline = SearchPipeline(tmp_path / "cache")
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=pipeline)
    monkeypatch.setattr("synthex_platform.retrieval.serper_client.requests.post", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        service.execute(job_id, pipeline=pipeline)
    service.jobs.reconcile_uncertain(job_id)
    ref = service.sources.publish_artifact(b'{"organic": []}', category="search")
    args = _reconcile_args(service, job_id, decision="RESULT_RECOVERED", artifact_ref=ref)
    service.reconcile(job_id, **args)
    assert service.jobs.get(job_id)["state"] == "WAITING_PROVIDER"
    with pytest.raises(ValueError, match="query differs"):
        service.execute(job_id, pipeline=SearchPipeline(tmp_path / "cache2", query="changed", network_allowed=False))
    assert service.jobs.get(job_id)["state"] == "WAITING_PROVIDER"
    monkeypatch.setattr("synthex_platform.retrieval.serper_client.requests.post", lambda *a, **k: pytest.fail("unexpected search network"))
    service.execute(job_id, pipeline=SearchPipeline(tmp_path / "cache2", network_allowed=False))
    assert service.jobs.get(job_id)["state"] == "SUCCEEDED"


def test_conflicting_external_outcome_is_rejected(tmp_path):
    service = _service(tmp_path)
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=SearchPipeline(tmp_path / "cache"))
    service.jobs.transition(job_id, "RUNNING")
    service.jobs.transition(job_id, "WAITING_PROVIDER")
    service.jobs.external_intent(job_id, action_id="search-1", service="serper",
                                 operation="search", request_hash="a" * 64)
    first = service.sources.publish_artifact(b'{"organic": []}', category="search")
    second = service.sources.publish_artifact(b'{"organic": [1]}', category="search")
    service.jobs.external_outcome(job_id, action_id="search-1", response_ref=first)
    with pytest.raises(ValueError, match="no matching intent"):
        service.jobs.external_outcome(job_id, action_id="search-1", response_ref=second)
    assert service.jobs.get(job_id)["external_actions"][0]["response_artifact_id"] == first


def test_confirmed_no_search_result_requires_later_explicit_resume(tmp_path, monkeypatch):
    service = _service(tmp_path)
    pipeline = SearchPipeline(tmp_path / "cache")
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=pipeline)
    monkeypatch.setattr("synthex_platform.retrieval.serper_client.requests.post", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        service.execute(job_id, pipeline=pipeline)
    service.jobs.reconcile_uncertain(job_id)
    service.reconcile(job_id, **_reconcile_args(service, job_id, decision="CONFIRMED_NO_RESULT"))
    assert service.jobs.get(job_id)["state"] == "WAITING_PROVIDER"
    with pytest.raises(ValueError, match="new search requires"):
        service.execute(job_id, pipeline=SearchPipeline(tmp_path / "cache2", network_allowed=False))
    calls = []
    monkeypatch.setattr("synthex_platform.retrieval.serper_client.requests.post", _fake_http(calls))
    service.resume_safe(job_id, action_id=RESUME_1, reason="operator_requested",
                        pipeline=SearchPipeline(tmp_path / "cache2", network_allowed=False))
    assert len(calls) == 1
    assert service.jobs.get(job_id)["state"] == "SUCCEEDED"


def test_confirmed_search_http_failure_and_raw_before_json_parse(tmp_path, monkeypatch):
    service = _service(tmp_path)
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=SearchPipeline(tmp_path / "cache"))
    calls = []
    monkeypatch.setattr("synthex_platform.retrieval.serper_client.requests.post", _fake_http(calls, error=True))
    with pytest.raises(requests.HTTPError):
        service.execute(job_id, pipeline=SearchPipeline(tmp_path / "cache"))
    action = service.jobs.get(job_id)["external_actions"][0]
    assert action["status"] == "FAILED_CONFIRMED"
    assert service.jobs.get(job_id)["state"] == "FAILED"
    second = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=SearchPipeline(tmp_path / "cache2"))
    monkeypatch.setattr("synthex_platform.retrieval.serper_client.requests.post", _fake_http(calls, body=b"not-json"))
    with pytest.raises(json.JSONDecodeError):
        service.execute(second, pipeline=SearchPipeline(tmp_path / "cache2"))
    raw = service.jobs.get(second)["external_actions"][0]
    assert raw["status"] == "RESULT_PERSISTED"
    assert service.sources.load_artifact(raw["response_artifact_id"], category="search") == b"not-json"


def test_operator_api_gate_preconditions_and_projection(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHEX_JOB_LOG_PATH", str(tmp_path / "jobs" / "events.jsonl"))
    monkeypatch.setattr(api, "store", JsonlArchiveStore(tmp_path / "archives.jsonl"))
    client = TestClient(api.app)
    assert client.post("/v1/jobs/missing/resume", json={"action_id": RESUME_1}).status_code == 403
    monkeypatch.setenv("SYNTHEX_OPERATOR_API_ENABLED", "true")
    assert client.post("/v1/jobs/missing/resume", json={"action_id": RESUME_1}).status_code == 404
    service = _service(tmp_path)
    job_id = service.submit(PDF, filename="C:\\private\\paper.pdf", domain="batteries", pipeline=_FakePipeline())
    _provider_intent(service, job_id)
    service.jobs.reconcile_uncertain(job_id)
    assert client.post(f"/v1/jobs/{job_id}/resume", json={"action_id": RESUME_1}).status_code == 409
    args = _reconcile_args(service, job_id, decision="OUTCOME_UNKNOWN")
    response = client.post(f"/v1/jobs/{job_id}/reconcile", json=args)
    assert response.status_code == 200
    assert "C:\\private" not in response.text
    assert "prompt:paper" not in response.text
    assert response.json()["job"]["reconciliation_target"]["request_hash"] == _provider_hash()


def test_operator_streamlit_controls_are_state_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHEX_DEVELOPER_MODE", "true")
    monkeypatch.setenv("SYNTHEX_OPERATOR_ACTIONS_ENABLED", "true")
    monkeypatch.setenv("SYNTHEX_JOB_LOG_PATH", str(tmp_path / "jobs" / "events.jsonl"))
    service = _service(tmp_path)
    job_id = service.submit(PDF, filename="paper.pdf", domain="batteries", pipeline=_FakePipeline())
    at = AppTest.from_file(Path(__file__).resolve().parents[1] / "platform_app.py", default_timeout=30).run()
    at.sidebar.radio[0].set_value("Developer · System audit").run()
    assert not at.exception
    assert any(button.label == "Resume safe job" for button in at.button)
    _provider_intent(service, job_id)
    service.jobs.reconcile_uncertain(job_id)
    at.run()
    assert not at.exception
    assert not any(button.label == "Resume safe job" for button in at.button)
    assert any(button.label == "Record reconciliation decision" for button in at.button)
