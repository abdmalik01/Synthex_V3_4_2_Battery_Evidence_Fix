from __future__ import annotations

import json
from hashlib import sha256
import os
from types import SimpleNamespace

import pytest

from synthex_platform.benchmarks.provider_artifacts import ProviderArtifactRecorder, _io_path
from synthex_platform.benchmarks import provider_artifacts
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction.domain_extractor import (
    DomainGeminiExtractor,
    StructuredExtractionValidationError,
)


def _invalid_extractor(responses: list[str], recorder: ProviderArtifactRecorder):
    class FakeModels:
        def __init__(self):
            self.calls = 0

        def generate_content(self, **_kwargs):
            response = responses[self.calls]
            self.calls += 1
            return SimpleNamespace(text=response)

    extractor = DomainGeminiExtractor.__new__(DomainGeminiExtractor)
    extractor.registry = DomainRegistry()
    extractor.model = "gemini-test"
    extractor.requested_model = "gemini-test"
    extractor.fallback_models = None
    extractor.provider_mode = "benchmark"
    extractor.client = SimpleNamespace(models=FakeModels())
    extractor.artifact_sink = recorder
    return extractor


def test_invalid_raw_and_repair_bodies_survive_validation_failure(tmp_path):
    raw = json.dumps({"source": {"title": "raw", "unsupported": 1}, "materials": []})
    repair = json.dumps({"source": {"title": "repair", "unsupported": 2}, "materials": []})
    recorder = ProviderArtifactRecorder(tmp_path / "attempt-1", model="gemini-test", attempt=1)
    extractor = _invalid_extractor([raw, repair], recorder)

    with pytest.raises(StructuredExtractionValidationError):
        extractor.extract_text("fixture", "generic")

    root = tmp_path / "attempt-1"
    assert (root / "raw_response.txt").read_text(encoding="utf-8") == raw
    assert json.loads((root / "parsed_response.json").read_text(encoding="utf-8"))["source"]["title"] == "raw"
    assert (root / "repair_response.txt").read_text(encoding="utf-8") == repair
    assert json.loads((root / "repair_parsed_response.json").read_text(encoding="utf-8"))["source"]["title"] == "repair"
    assert json.loads((root / "raw_validation_report.json").read_text(encoding="utf-8"))["valid"] is False
    assert json.loads((root / "repaired_validation_report.json").read_text(encoding="utf-8"))["valid"] is False
    assert json.loads((root / "admission_result.json").read_text(encoding="utf-8"))["admitted"] is False
    assert json.loads((root / "provider_status.json").read_text(encoding="utf-8"))["attempts"][-1]["phase"] == "schema_repair"


def test_raw_provider_body_is_immutable(tmp_path):
    recorder = ProviderArtifactRecorder(tmp_path / "attempt-1", model="gemini-test", attempt=1)
    recorder("raw_response", "first")
    recorder("raw_response", "first")
    with pytest.raises(RuntimeError, match="Refusing to overwrite immutable"):
        recorder("raw_response", "second")
    assert (tmp_path / "attempt-1" / "raw_response.txt").read_text(encoding="utf-8") == "first"


def test_failed_immutable_publication_leaves_no_partial_raw_artifact(tmp_path, monkeypatch):
    recorder = ProviderArtifactRecorder(tmp_path / "attempt-1", model="gemini-test", attempt=1)
    raw_path = tmp_path / "attempt-1" / "raw_response.txt"

    def fail_publish(_source, _target):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(provider_artifacts.os, "link", fail_publish)
    with pytest.raises(OSError, match="simulated publication failure"):
        recorder("raw_response", "body that must not be partial")

    assert not raw_path.exists()
    assert not (tmp_path / "attempt-1" / "raw_response_sha256.json").exists()
    assert not list((tmp_path / "attempt-1").glob("*.tmp"))


def test_provider_body_digest_matches_exact_persisted_bytes(tmp_path):
    body = "first line\nsecond line\n"
    recorder = ProviderArtifactRecorder(tmp_path / "attempt-1", model="gemini-test", attempt=1)
    recorder("raw_response", body)

    root = tmp_path / "attempt-1"
    persisted = (root / "raw_response.txt").read_bytes()
    digest = json.loads((root / "raw_response_sha256.json").read_text(encoding="utf-8"))
    assert persisted == body.encode("utf-8")
    assert digest["sha256"] == sha256(persisted).hexdigest()


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length path regression")
def test_provider_artifacts_survive_windows_paths_over_260_characters(tmp_path):
    padding = "x" * max(1, 225 - len(str(tmp_path.resolve())))
    root = tmp_path / padding / "attempt-1"
    recorder = ProviderArtifactRecorder(root, model="gemini-test", attempt=1)
    recorder("raw_response", '{"ok": true}')
    recorder("response_metadata", {"latency_ms": 1.0})
    recorder("parsed_response", {"ok": True})
    recorder("repair_response", '{"repaired": true}')
    recorder("repair_parsed_response", {"repaired": True})
    recorder("repaired_validation_report", {"valid": True, "errors": []})

    assert len(str((root / "raw_response_sha256.json").resolve())) >= 260
    assert json.loads(_io_path(root / "parsed_response.json").read_text(encoding="utf-8")) == {"ok": True}
    assert json.loads(_io_path(root / "repair_parsed_response.json").read_text(encoding="utf-8")) == {"repaired": True}
