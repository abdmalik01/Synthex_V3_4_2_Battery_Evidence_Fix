"""Small local multi-process JSONL journal with explicit tail recovery.

The lock is held across validation, identity checks, append/fsync, and reads.
It coordinates local processes sharing a filesystem; it is not a distributed lock.
"""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Iterator
from uuid import uuid4


class CorruptJsonlError(ValueError):
    """The log contains an incomplete or malformed record and was not changed."""


_thread_locks: dict[str, threading.RLock] = {}
_thread_locks_guard = threading.Lock()


def _io_path(path: Path) -> str:
    value = str(path.resolve())
    if os.name == "nt" and len(value) >= 240 and not value.startswith("\\\\?\\"):
        return "\\\\?\\" + value
    return value


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    key = os.path.normcase(str(path.resolve()))
    with _thread_locks_guard:
        thread_lock = _thread_locks.setdefault(key, threading.RLock())
    with thread_lock:
        lock_path = path.with_name(path.name + ".lock")
        fd = os.open(_io_path(lock_path), os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                deadline = time.monotonic() + 60
                while True:
                    try:
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"Timed out waiting for JSONL lock: {path.name}")
                        time.sleep(0.02)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _decode_records(data: bytes) -> tuple[list[dict[str, Any]], int, str | None]:
    rows: list[dict[str, Any]] = []
    valid_end = 0
    for chunk in data.splitlines(keepends=True):
        if not chunk.endswith(b"\n"):
            return rows, valid_end, "unterminated"
        try:
            row = json.loads(chunk.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return rows, valid_end, "malformed"
        if not isinstance(row, dict):
            return rows, valid_end, "non_object"
        rows.append(row)
        valid_end += len(chunk)
    return rows, valid_end, None


class JsonlLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _ensure_parent(self) -> None:
        Path(_io_path(self.path.parent)).mkdir(parents=True, exist_ok=True)

    def _read_locked(self) -> tuple[list[dict[str, Any]], bytes]:
        try:
            data = Path(_io_path(self.path)).read_bytes()
        except FileNotFoundError:
            return [], b""
        rows, end, issue = _decode_records(data)
        if issue is not None:
            raise CorruptJsonlError(
                f"{self.path.name}: {issue} JSONL record at byte {end}; "
                "call recover_trailing_partial explicitly after inspecting the audit"
            )
        return rows, data

    def read_all(self) -> list[dict[str, Any]]:
        if not Path(_io_path(self.path)).exists():
            return []
        with _exclusive_lock(self.path):
            rows, _ = self._read_locked()
            return rows

    def _write_record(self, record: bytes) -> None:
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_BINARY", 0)
        fd = os.open(_io_path(self.path), flags, 0o600)
        try:
            cursor = 0
            while cursor < len(record):
                written = os.write(fd, record[cursor:])
                if written <= 0:
                    raise OSError("Zero-byte JSONL append")
                cursor += written
            os.fsync(fd)
        finally:
            os.close(fd)

    def append(self, row: dict[str, Any], *, identity: Callable[[dict[str, Any]], str] | None = None) -> bool:
        if not isinstance(row, dict):
            raise TypeError("JSONL rows must be objects")
        record = (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        self._ensure_parent()
        with _exclusive_lock(self.path):
            rows, _ = self._read_locked()
            if identity is not None:
                key = identity(row)
                if not key:
                    raise ValueError("JSONL record identity cannot be empty")
                for existing in rows:
                    if identity(existing) == key:
                        if existing == row:
                            return False
                        raise ValueError(f"conflicting JSONL record identity: {key}")
            self._write_record(record)
            return True

    def transact(self, build: Callable[[list[dict[str, Any]]], dict[str, Any] | None]) -> dict[str, Any] | None:
        """Validate current rows and append one event under the same process lock."""
        self._ensure_parent()
        with _exclusive_lock(self.path):
            rows, _ = self._read_locked()
            row = build(rows)
            if row is None:
                return None
            if not isinstance(row, dict):
                raise TypeError("JSONL transaction must yield an object")
            record = (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            self._write_record(record)
            return row

    def recover_trailing_partial(self) -> dict[str, Any]:
        """Explicitly repair only the final segment, retaining original bytes + audit.

        An unterminated but valid object is newline-completed; an invalid tail is
        removed. Interior corruption is never repaired automatically.
        """
        with _exclusive_lock(self.path):
            original = Path(_io_path(self.path)).read_bytes()
            rows, end, issue = _decode_records(original)
            if issue is None:
                raise ValueError("JSONL log has no trailing issue to recover")
            tail = original[end:]
            if b"\n" in tail.rstrip(b"\n") or (tail.endswith(b"\n") and issue != "unterminated"):
                raise CorruptJsonlError("Interior or newline-terminated corruption requires manual investigation")
            action = "discard_malformed_tail"
            repaired = original[:end]
            if issue == "unterminated":
                try:
                    candidate = json.loads(tail.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    candidate = None
                if isinstance(candidate, dict):
                    repaired = original + b"\n"
                    action = "complete_valid_line"
            suffix = uuid4().hex
            backup = self.path.with_name(f"{self.path.name}.recovery-{suffix}.bak")
            audit_path = self.path.with_name(f"{self.path.name}.recovery-{suffix}.json")
            with open(_io_path(backup), "xb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            audit = {
                "action": action,
                "issue": issue,
                "original_sha256": sha256(original).hexdigest(),
                "repaired_sha256": sha256(repaired).hexdigest(),
                "preserved_valid_rows": len(rows),
                "original_bytes": len(original),
                "repaired_bytes": len(repaired),
                "backup_path": str(backup),
                "audit_path": str(audit_path),
            }
            with open(_io_path(audit_path), "xb") as stream:
                stream.write((json.dumps(audit, indent=2) + "\n").encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            with open(_io_path(self.path), "r+b") as stream:
                stream.seek(0)
                stream.write(repaired)
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
            return audit
