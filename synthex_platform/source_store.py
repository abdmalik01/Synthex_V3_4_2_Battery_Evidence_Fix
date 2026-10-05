"""Immutable, content-addressed local source and job artifact storage."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import re
import tempfile

from synthex_platform.core.identifiers import source_id as make_source_id
from synthex_platform.storage.atomic_jsonl import _io_path


class SourceIntegrityError(ValueError):
    pass


def _publish(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=_io_path(path.parent), prefix=".publish-", delete=False) as handle:
            temporary = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, _io_path(path))
        except FileExistsError:
            if Path(_io_path(path)).read_bytes() != data:
                raise SourceIntegrityError("existing immutable artifact differs from expected content")
        # The directory entry is durable on POSIX after syncing the containing directory.
        if os.name != "nt":
            fd = os.open(_io_path(path.parent), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


class SourceStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, digest: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("invalid source digest")
        return self.root / "sources" / f"{digest}.pdf"

    def publish(self, data: bytes, *, filename: str, media_type: str = "application/pdf") -> dict:
        if not isinstance(data, bytes) or not data or not data.startswith(b"%PDF-"):
            raise ValueError("source must be nonempty PDF bytes")
        if media_type != "application/pdf":
            raise ValueError("unsupported source media type")
        digest = sha256(data).hexdigest()
        _publish(self._path(digest), data)
        safe_filename = Path(filename.replace("\\", "/")).name[:255]
        if not safe_filename or any(ord(char) < 32 for char in safe_filename):
            safe_filename = "uploaded.pdf"
        return {
            "source_id": make_source_id(checksum=digest),
            "sha256": digest,
            "filename": safe_filename,
            "media_type": media_type,
            "byte_size": len(data),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "artifact_ref": f"sha256:{digest}",
        }

    def load(self, source: dict) -> Path:
        digest = source["sha256"]
        path = self._path(digest)
        data = Path(_io_path(path)).read_bytes()
        if sha256(data).hexdigest() != digest or len(data) != source["byte_size"]:
            raise SourceIntegrityError("durable source integrity check failed")
        if source.get("source_id") != make_source_id(checksum=digest):
            raise SourceIntegrityError("source identity mismatch")
        return path

    def publish_artifact(self, payload: bytes, *, category: str) -> str:
        if category not in {"raw", "validated", "search"}:
            raise ValueError("invalid artifact category")
        digest = sha256(payload).hexdigest()
        _publish(self.root / category / digest, payload)
        return f"sha256:{digest}"

    def load_artifact(self, ref: str, *, category: str) -> bytes:
        if not ref.startswith("sha256:"):
            raise ValueError("invalid artifact reference")
        digest = ref[7:]
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None or category not in {"raw", "validated", "search"}:
            raise ValueError("invalid artifact reference")
        data = (self.root / category / digest).read_bytes()
        if sha256(data).hexdigest() != digest:
            raise SourceIntegrityError("durable artifact integrity check failed")
        return data
