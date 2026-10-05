import json
from pathlib import Path

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from synthex_platform.api import app
from synthex_platform.jobs import JobStore
from synthex_platform.system_status import SystemAuditReader


def _write(root, name, content):
    (root / name).write_text(json.dumps(content), encoding="utf-8")


def test_read_only_projection_and_biomaterials_semantics(tmp_path):
    root = tmp_path / "audit"
    root.mkdir()
    _write(root, "domain_status.json", {"domains": [
        {"domain": "biomaterials", "scientific_status": "deterministically_closed", "freeze_status": "pending_live_provider_gate", "benchmark_case_count": 8, "canonical_outputs": 158, "invariant_pass_count": 40, "live_provider_gate": False, "known_limitations": ["No provider payload"]},
        {"domain": "membranes", "scientific_status": "frozen_deterministic_scope", "freeze_status": "frozen", "benchmark_case_count": 6, "canonical_outputs": 120, "invariant_pass_count": 30, "live_provider_gate": True},
    ]})
    _write(root, "benchmark_registry.json", {"cases": [
        {"domain": "biomaterials", "case_id": "BIO-GOLD-A", "source": "C:\\private\\paper.pdf", "doi": "10.1000/example", "benchmark_type": "gold", "deterministic_output_count": 10, "experiments": 5, "calculations": 1, "source_hashes": {"source_sha256": "abc"}, "hash_matches": {"source_sha256": ["C:\\private\\paper.pdf"]}},
    ]})
    _write(root, "provider_matrix.json", {"runs": [
        {"domain": "biomaterials", "case": "BIO-GOLD-A", "provider": "gemini", "exact_model": "models/gemini-test", "payload_returned": False, "raw_scientific_score": 0.0, "provider_error_classes": ["rate_limited"], "report_path": "C:\\private\\secret.json"},
    ]})
    _write(root, "scientific_safety.json", {"by_domain": {"biomaterials": {"reported": {"ownership_contamination": [], "evidence_violations": []}, "basis_kind": "closure_observed"}, "membranes": {"reported": None, "basis_kind": None}}})
    _write(root, "worktree_audit.json", {"head": "1234567890", "branch": "main", "entries": [{"path": "C:\\private\\secret.txt"}]})
    jobs = JobStore(tmp_path / "jobs.jsonl")
    jobs.create("job-1", run_id="run-1", task_type="extraction", domain="biomaterials", source_id="BIO-GOLD-A", provider="gemini", model="models/gemini-test")
    reader = SystemAuditReader(root, jobs=jobs)
    status = reader.status()
    assert status["domains"][0]["display_status"] == "DETERMINISTICALLY CLOSED · LIVE GATE PENDING · NOT FROZEN"
    assert status["domains"][1]["freeze_status"] == "frozen"
    assert reader.benchmarks("membranes")["cases"] == []
    assert reader.provider_runs()["runs"][0]["scientific_score"] == "N/A"
    assert reader.safety()["domains"]["membranes"]["ownership_contamination"] == "not standardized"
    assert reader.jobs()["jobs"][0]["state"] == "PENDING"
    jobs.create("job-2", run_id="run-2", task_type="provider_extraction", domain="biomaterials", source_id="BIO-GOLD-A")
    jobs.record_failure("job-2", RuntimeError("HTTP 429 private_token"))
    assert reader.job("job-2")["error_summary"] == "provider rate limited"
    text = json.dumps({"status": status, "benchmarks": reader.benchmarks(), "providers": reader.provider_runs(), "safety": reader.safety(), "jobs": reader.jobs()})
    assert "C:\\private" not in text
    assert "secret" not in text
    assert "private_token" not in text


def test_missing_and_malformed_audit_files_are_cleanly_unavailable(tmp_path):
    reader = SystemAuditReader(tmp_path)
    assert reader.status()["status"] == "unavailable"
    (tmp_path / "provider_matrix.json").write_text("{broken", encoding="utf-8")
    assert reader.provider_runs()["status"] == "unavailable"


def test_read_only_api_filtering_and_empty_results(tmp_path, monkeypatch):
    root = tmp_path / "audit"
    root.mkdir()
    _write(root, "benchmark_registry.json", {"cases": [{"domain": "membranes", "case_id": "MEM-A"}]})
    monkeypatch.setenv("SYNTHEX_SYSTEM_AUDIT_ROOT", str(root))
    monkeypatch.setenv("SYNTHEX_JOB_LOG_PATH", str(tmp_path / "jobs.jsonl"))
    client = TestClient(app)
    assert client.get("/v1/system/benchmarks/membranes").json()["case_count"] == 1
    assert client.get("/v1/system/benchmarks/biomaterials").json()["cases"] == []
    assert client.get("/v1/system/jobs/missing").status_code == 404
    assert client.get("/v1/system/status").json()["status"] == "unavailable"
    assert not (tmp_path / "jobs.jsonl").exists()
    assert not (tmp_path / "jobs.jsonl.lock").exists()


def test_real_audit_snapshot_preserves_ten_domain_and_no_payload_semantics():
    root = Path(__file__).resolve().parents[1] / "benchmark" / "system_audit"
    reader = SystemAuditReader(root)
    status = reader.status()
    assert status["status"] == "available"
    assert len(status["domains"]) == 10
    bio = next(row for row in status["domains"] if row["domain"] == "biomaterials")
    assert bio["display_status"] == "DETERMINISTICALLY CLOSED · LIVE GATE PENDING · NOT FROZEN"
    assert bio["live_provider_gate"] is False
    assert any(row["freeze_status"] == "frozen" for row in status["domains"])
    runs = reader.provider_runs("biomaterials")["runs"]
    assert runs and all(row["scientific_score"] == "N/A" for row in runs)
    assert all(row["payload"] is False for row in runs)


def test_streamlit_system_audit_page_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHEX_DEVELOPER_MODE", "true")
    monkeypatch.setenv("SYNTHEX_JOB_LOG_PATH", str(tmp_path / "jobs.jsonl"))
    app_file = Path(__file__).resolve().parents[1] / "platform_app.py"
    at = AppTest.from_file(app_file, default_timeout=30).run()
    at.sidebar.radio[0].set_value("Developer · System audit").run()
    assert not at.exception
    assert any(item.value == "System audit" for item in at.title)
    assert len(at.tabs) == 5
    assert "DETERMINISTICALLY CLOSED" in at.dataframe[0].value.to_string()
    assert not at.button
    assert not (tmp_path / "jobs.jsonl").exists()


def test_home_is_product_focused_and_path_free(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHEX_JOB_LOG_PATH", str(tmp_path / "jobs.jsonl"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app_file = Path(__file__).resolve().parents[1] / "platform_app.py"
    at = AppTest.from_file(app_file, default_timeout=30).run()
    assert not at.exception
    assert any(item.value == "Synthex" for item in at.title)
    assert {button.label for button in at.button} >= {"Analyze papers", "Discover papers"}
    visible = " ".join(item.value for item in (*at.subheader, *at.markdown, *at.caption, *at.info))
    assert "From paper to insight" in visible
    assert "Scientific coverage" not in visible
    assert "Recent durable jobs" not in visible
    assert "configured" not in visible
    assert not at.metric
    assert "C:\\Users\\" not in visible
    assert not (tmp_path / "jobs.jsonl").exists()


def test_home_does_not_depend_on_system_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHEX_SYSTEM_AUDIT_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNTHEX_JOB_LOG_PATH", str(tmp_path / "jobs.jsonl"))
    app_file = Path(__file__).resolve().parents[1] / "platform_app.py"
    for malformed in (False, True):
        if malformed:
            (tmp_path / "domain_status.json").write_text("{broken", encoding="utf-8")
        at = AppTest.from_file(app_file, default_timeout=30).run()
        assert not at.exception
        assert any(item.value == "Synthex" for item in at.title)
        assert {button.label for button in at.button} >= {"Analyze papers", "Discover papers"}
        assert not at.metric
        assert not at.info
        assert not (tmp_path / "jobs.jsonl").exists()


def test_analyze_page_keeps_pdf_upload_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("SYNTHEX_JOB_LOG_PATH", str(tmp_path / "jobs.jsonl"))
    app_file = Path(__file__).resolve().parents[1] / "platform_app.py"
    at = AppTest.from_file(app_file, default_timeout=30).run()
    at.sidebar.radio[0].set_value("Analyze Papers").run()
    assert not at.exception
    assert any(item.value == "Analyze papers" for item in at.header)
    assert any(item.value == "Upload source PDFs" for item in at.subheader)
    assert "st.file_uploader(" in app_file.read_text(encoding="utf-8")
    assert not (tmp_path / "jobs.jsonl").exists()
