import json
from pathlib import Path

from benchmark.provider_audit.build_history import REPO, build
from synthex_platform.benchmarks.optional_evidence import inspect_optional_raw_artifact


def test_provider_history_is_metadata_only_and_reproducible():
    package = build()
    stored = json.loads((REPO / "benchmark/provider_audit/provider_history.json").read_text(encoding="utf-8"))
    if package["runs"]:
        assert package["runs"] == stored["runs"]
    assert len({r["report_path"] for r in stored["runs"]}) == len(stored["runs"])
    assert all("offline" not in r["report_path"] and "pytest" not in r["report_path"] for r in stored["runs"])
    assert all(r["raw_scientific_score"] is None for r in stored["runs"] if r["payload_returned"] is False)
    assert all(r["exact_model"] for r in stored["runs"])
    for row in stored["runs"]:
        for artifact in row["raw_artifacts"]:
            state = inspect_optional_raw_artifact(REPO, artifact["path"], artifact["sha256"])
            assert state["integrity"] in {"VERIFIED", "NOT_AVAILABLE_LOCALLY"}
    assert not any("provider_message" in row or "raw_response_body" in row for row in stored["runs"])


def test_gate_matrix_counts_and_absent_domains():
    package = build()
    matrix = json.loads((REPO / "benchmark/provider_audit/provider_gate_matrix.json").read_text(encoding="utf-8"))
    if package["runs"]:
        assert package["matrix"] == matrix
    stored = json.loads((REPO / "benchmark/provider_audit/provider_history.json").read_text(encoding="utf-8"))
    assert sum(cell["runs"] for cell in matrix.values()) == len(stored["runs"])
    assert "batteries" not in matrix and "catalysis" not in matrix
    assert all(cell["payload_yes"] + cell["payload_no"] + cell["payload_unknown"] == cell["runs"] for cell in matrix.values())
