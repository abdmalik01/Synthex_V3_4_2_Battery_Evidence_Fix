from hashlib import sha256

import pytest

from synthex_platform.benchmarks.optional_evidence import inspect_optional_raw_artifact


def test_optional_provider_body_absent_is_unavailable_not_failed(tmp_path):
    expected = sha256(b"historical response").hexdigest()
    assert inspect_optional_raw_artifact(tmp_path, "output/run/raw_response.txt", expected) == {
        "RAW_PROVIDER_ARTIFACT_AVAILABLE": False,
        "integrity": "NOT_AVAILABLE_LOCALLY",
    }


def test_optional_provider_body_present_requires_exact_digest(tmp_path):
    artifact = tmp_path / "output/run/raw_response.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"historical response")
    expected = sha256(artifact.read_bytes()).hexdigest()
    assert inspect_optional_raw_artifact(tmp_path, "output/run/raw_response.txt", expected) == {
        "RAW_PROVIDER_ARTIFACT_AVAILABLE": True,
        "integrity": "VERIFIED",
    }
    artifact.write_bytes(b"corrupted response")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        inspect_optional_raw_artifact(tmp_path, "output/run/raw_response.txt", expected)


@pytest.mark.parametrize("path", ["../outside.txt", "C:\\Users\\someone\\raw.txt"])
def test_optional_provider_body_must_be_repository_relative(tmp_path, path):
    with pytest.raises(ValueError, match="repository-relative"):
        inspect_optional_raw_artifact(tmp_path, path, sha256(b"body").hexdigest())
