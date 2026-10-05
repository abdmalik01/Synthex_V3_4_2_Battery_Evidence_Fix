"""Persistence-first artifacts for controlled provider benchmarks."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from synthex_platform.providers import redact_secrets


_TEXT_EVENTS = {
    "raw_response": "raw_response.txt",
    "repair_request": "repair_request.txt",
    "repair_response": "repair_response.txt",
}
_JSON_EVENTS = {
    "parsed_response": "parsed_response.json",
    "repair_parsed_response": "repair_parsed_response.json",
    "raw_validation_report": "raw_validation_report.json",
    "repaired_validation_report": "repaired_validation_report.json",
    "provider_status": "provider_status.json",
    "admission_result": "admission_result.json",
    "request_metadata": "request_metadata.json",
    "response_metadata": "response_metadata.json",
    "scientific_score": "scientific_score.json",
}
_IMMUTABLE_EVENTS = {
    "raw_response", "parsed_response", "repair_request", "repair_response",
    "repair_parsed_response", "request_metadata", "response_metadata",
    "raw_validation_report", "repaired_validation_report", "scientific_score",
    "admission_result",
}
_SANITIZED_JSON_EVENTS = {
    "provider_status", "request_metadata", "response_metadata",
    "raw_validation_report", "repaired_validation_report", "admission_result",
}
_RAW_REQUIRED_EVENTS = {
    "parsed_response", "raw_validation_report", "response_metadata",
    "repair_request", "repair_response", "repair_parsed_response",
    "repaired_validation_report", "scientific_score", "admission_result",
}
_REPAIR_REQUIRED_EVENTS = {"repair_parsed_response", "repaired_validation_report"}
_SENSITIVE_KEYS = {
    "api_key", "authorization", "credential", "credentials", "secret",
    "token", "access_token", "refresh_token",
}


def _io_path(path: Path) -> Path:
    """Use an extended-length Windows path without changing stored artifact paths."""
    resolved = path.resolve()
    text = str(resolved)
    if os.name == "nt" and len(text) >= 240 and not text.startswith("\\\\?\\"):
        return Path("\\\\?\\" + text)
    return path


def _sanitize_metadata(value: Any, *, key: str | None = None) -> Any:
    if key and key.casefold() in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {
            item_key: _sanitize_metadata(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_metadata(item) for item in value]
    return value


class ProviderArtifactRecorder:
    """Write provider lifecycle stages while keeping response bodies immutable."""

    def __init__(self, root: str | Path, *, model: str, attempt: int, provider: str = "gemini", case_id: str | None = None, run_id: str | None = None, input_mode: str = "source_text") -> None:
        self.root = Path(root)
        _io_path(self.root).mkdir(parents=True, exist_ok=True)
        self.model = model
        self.attempt = attempt
        self._write_json(
            self.root / "attempt_metadata.json",
            {
                "attempt": attempt,
                "attempt_id": f"attempt-{attempt}",
                "provider_name": provider,
                "model": model,
                "configured_model_id": model,
                "case_id": case_id,
                "run_id": run_id,
                "input_mode": input_mode,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            immutable=True,
        )

    @staticmethod
    def _serialized(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, indent=2, ensure_ascii=False)

    def _write_text(self, path: Path, value: str, *, immutable: bool) -> None:
        io_path = _io_path(path)
        encoded = value.encode("utf-8")
        if immutable and io_path.exists():
            existing = io_path.read_bytes()
            if existing != encoded:
                raise RuntimeError(f"Refusing to overwrite immutable provider artifact: {path}")
            return
        # Prepare exact bytes off-path so an interrupted write cannot publish
        # a partial response. Hard-link publication preserves create-only
        # semantics for immutable artifacts even with concurrent writers.
        temporary = _io_path(path.with_name(f".{path.name}.{uuid4().hex}.tmp"))
        try:
            with temporary.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if immutable:
                try:
                    os.link(temporary, io_path)
                except FileExistsError:
                    if io_path.read_bytes() != encoded:
                        raise RuntimeError(f"Refusing to overwrite immutable provider artifact: {path}")
            else:
                os.replace(temporary, io_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _write_json(self, path: Path, value: Any, *, immutable: bool = False) -> None:
        self._write_text(
            path,
            json.dumps(value, indent=2, ensure_ascii=False) + "\n",
            immutable=immutable,
        )

    def __call__(self, event: str, payload: Any) -> None:
        if event in _RAW_REQUIRED_EVENTS and not _io_path(self.root / "raw_response.txt").exists():
            raise RuntimeError(f"Provider artifact {event} cannot precede raw_response persistence")
        if event in _REPAIR_REQUIRED_EVENTS and not _io_path(self.root / "repair_response.txt").exists():
            raise RuntimeError(f"Provider artifact {event} cannot precede repair_response persistence")
        if event in _TEXT_EVENTS:
            value = self._serialized(payload)
            self._write_text(
                self.root / _TEXT_EVENTS[event], value,
                immutable=event in _IMMUTABLE_EVENTS,
            )
            self._write_json(
                self.root / f"{event}_sha256.json",
                {"sha256": sha256(value.encode("utf-8")).hexdigest()},
            )
            return
        if event in _JSON_EVENTS:
            if event in _SANITIZED_JSON_EVENTS:
                payload = _sanitize_metadata(payload)
            self._write_json(
                self.root / _JSON_EVENTS[event], payload,
                immutable=event in _IMMUTABLE_EVENTS,
            )
            return
        raise ValueError(f"Unknown provider artifact event: {event}")


def create_live_run_root(case_root: str | Path) -> Path:
    """Create a non-overwriting UTC run directory and update a small latest pointer."""
    case_path = Path(case_root)
    runs = case_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_root = runs / stamp
    run_root.mkdir()
    (case_path / "latest_run.json").write_text(
        json.dumps({"run_id": stamp, "path": str(run_root)}, indent=2) + "\n",
        encoding="utf-8",
    )
    return run_root


def _path_component(value: str, *, max_length: int = 64) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")
    if not cleaned:
        raise ValueError("Provider artifact path component cannot be empty")
    if len(cleaned) <= max_length:
        return cleaned
    digest = sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"{cleaned[:max_length - len(digest) - 1]}-{digest}"


def create_provider_run_root(
    output_root: str | Path,
    *,
    case_id: str,
    provider_name: str,
    model_id: str,
    run_id: str | None = None,
) -> tuple[Path, str]:
    """Create a case/provider/model/run directory without touching historical layouts."""
    identifier = run_id or (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + "-"
        + uuid4().hex[:12]
    )
    root = (
        Path(output_root)
        / _path_component(case_id, max_length=32)
        / _path_component(provider_name, max_length=20)
        / _path_component(model_id, max_length=24)
        / _path_component(identifier, max_length=48)
    )
    root.mkdir(parents=True, exist_ok=False)
    return root, identifier


def read_provider_report(path: str | Path) -> dict[str, Any]:
    """Read current or historical Gemini reports into a lossless neutral envelope."""
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    configured_model_id = report.get("configured_model_id") or report.get("model_id") or report.get("requested_model")
    return {
        "provider_name": report.get("provider_name", "gemini"),
        "configured_model_id": configured_model_id,
        "model_id": report.get("actual_model") or report.get("model_id") or report.get("requested_model"),
        "provider_reported_model_id": report.get("provider_reported_model_id") or report.get("actual_model"),
        "run_id": report.get("run_id"),
        "case_id": report.get("case_id"),
        "status": report.get("status"),
        "attempts": report.get("attempts") or report.get("provider_attempts") or [],
        "raw_scientific_score": report.get("raw_scientific_score", report.get("raw_provider_scientific_score")),
        "canonical_admission": report.get("canonical_admission"),
        "original_report": report,
    }


def iter_complete_provider_reports(root: str | Path):
    """Yield only completed run reports; incomplete historical directories stay untouched."""
    yield from sorted(Path(root).glob("**/report.json"))


def inspect_provider_run(root: str | Path) -> dict[str, Any]:
    """Describe a provider run without treating an incomplete directory as a result."""
    path = Path(root)
    report = path / "report.json"
    marker = path / "incomplete_run.json"
    if report.exists():
        return {"status": "complete", "summary_eligible": True, "report_path": str(report)}
    if marker.exists():
        metadata = json.loads(marker.read_text(encoding="utf-8"))
        return {**metadata, "status": "incomplete", "summary_eligible": False}
    return {"status": "incomplete_unmarked", "summary_eligible": False}
