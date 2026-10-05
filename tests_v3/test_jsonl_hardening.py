from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.storage import JsonlArchiveStore
from synthex_platform.storage.atomic_jsonl import CorruptJsonlError, JsonlLog
from tests_v3.test_platform import make_archive


def test_legacy_check_then_append_race_reproduces_duplicate_identity(tmp_path):
    """Both workers can pass the former API check before either writes."""
    from threading import Barrier

    path = tmp_path / "legacy.jsonl"
    store = JsonlArchiveStore(path)
    archive = make_archive()
    barrier = Barrier(2)

    def former_api_sequence(_):
        assert store.get(archive.metadata.archive_id) is None
        barrier.wait(timeout=5)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(archive.model_dump_json(exclude_none=True) + "\n")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(former_api_sequence, range(2)))
    assert store.count() == 2
    with pytest.raises(ValueError, match="duplicate historical"):
        store.rebuild_index()


def _process_append(args):
    path, archive_json, identifier = args
    archive = SynthexArchive.model_validate_json(archive_json)
    old_id = archive.metadata.archive_id
    archive.metadata.archive_id = identifier
    for relation in archive.relationships:
        if relation.subject_id == old_id:
            relation.subject_id = identifier
        if relation.object_id == old_id:
            relation.object_id = identifier
    return JsonlArchiveStore(path).append_unique(archive)


def test_concurrent_threads_and_processes_keep_complete_unique_lines(tmp_path):
    path = tmp_path / "archives.jsonl"
    source = make_archive().model_dump_json()
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(_process_append, [(path, source, f"thread-{i}") for i in range(32)]))
    with ProcessPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(_process_append, [(path, source, f"process-{i}") for i in range(24)]))
    data = path.read_bytes()
    assert data.endswith(b"\n")
    assert len(data.splitlines()) == 56
    assert JsonlArchiveStore(path).count() == 56
    assert len({json.loads(line)["metadata"]["archive_id"] for line in data.splitlines()}) == 56


def test_duplicate_archive_id_is_idempotent_only_for_identical_bytes(tmp_path):
    store = JsonlArchiveStore(tmp_path / "a.jsonl")
    archive = make_archive()
    assert store.append_unique(archive) is True
    assert store.append_unique(archive) is False
    changed = archive.model_copy(deep=True)
    changed.sources[0].title = "Different scientific content"
    with pytest.raises(ValueError, match="conflicting"):
        store.append_unique(changed)
    assert store.count() == 1
    assert store.rebuild_index() == {archive.metadata.archive_id: 0}


def test_historical_duplicate_identity_rejected_by_rebuilt_index(tmp_path):
    path = tmp_path / "a.jsonl"
    store = JsonlArchiveStore(path)
    archive = make_archive()
    store.append(archive)
    data = path.read_bytes()
    path.write_bytes(data + data)
    with pytest.raises(ValueError, match="duplicate historical"):
        store.rebuild_index()


@pytest.mark.parametrize("tail", [b'{"metadata":', b'\xff'])
def test_partial_or_malformed_tail_requires_explicit_recovery(tmp_path, tail):
    path = tmp_path / "a.jsonl"
    store = JsonlArchiveStore(path)
    store.append(make_archive())
    original = path.read_bytes() + tail
    path.write_bytes(original)
    with pytest.raises(CorruptJsonlError):
        store.count()
    with pytest.raises(CorruptJsonlError):
        store.append_unique(make_archive())
    assert path.read_bytes() == original
    audit = store.recover_trailing_partial()
    assert Path(audit["backup_path"]).read_bytes() == original
    assert Path(audit["audit_path"]).exists()
    assert store.count() == 1


def test_valid_unterminated_object_is_completed_not_discarded(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"id":"valid"}')
    log = JsonlLog(path)
    with pytest.raises(CorruptJsonlError):
        log.read_all()
    audit = log.recover_trailing_partial()
    assert audit["action"] == "complete_valid_line"
    assert log.read_all() == [{"id": "valid"}]


def test_reader_waits_for_writer_publication_and_does_not_see_partial_record(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    log = JsonlLog(path)
    log.append({"id": "first", "label": "β"})
    original = log._write_record
    from threading import Event, Thread
    entered, release = Event(), Event()

    def paused(record):
        entered.set()
        assert release.wait(5)
        original(record)

    monkeypatch.setattr(log, "_write_record", paused)
    writer = Thread(target=lambda: log.append({"id": "second", "label": "μ"}))
    writer.start()
    assert entered.wait(5)
    reader = Thread(target=lambda: list(JsonlLog(path).read_all()))
    reader.start()
    assert reader.is_alive()
    release.set()
    writer.join(5)
    reader.join(5)
    assert [r["id"] for r in log.read_all()] == ["first", "second"]


def test_long_path_and_non_ascii_content(tmp_path):
    path = tmp_path.joinpath(*(["nested_directory_abcdefghijk"] * 9), "unicode.jsonl")
    log = JsonlLog(path)
    log.append({"id": "μm-1", "text": "温度 ΔT = 25 °C"})
    assert log.read_all()[0]["text"] == "温度 ΔT = 25 °C"


def test_interrupted_before_fsync_does_not_claim_durable_success(tmp_path, monkeypatch):
    log = JsonlLog(tmp_path / "events.jsonl")
    def failed(_):
        raise OSError("simulated fsync interruption")
    monkeypatch.setattr("synthex_platform.storage.atomic_jsonl.os.fsync", failed)
    with pytest.raises(OSError, match="fsync"):
        log.append({"id": "possibly-written"})


def test_archive_api_returns_recovery_status_without_leaking_path(tmp_path, monkeypatch):
    import synthex_platform.api as api
    path = tmp_path / "private" / "archives.jsonl"
    path.parent.mkdir()
    path.write_bytes(b'{"partial":')
    monkeypatch.setattr(api, "store", JsonlArchiveStore(path))
    response = TestClient(api.app).post("/v1/archives", json=make_archive().model_dump(mode="json"))
    assert response.status_code == 503
    assert "private" not in response.text
