from __future__ import annotations

from pathlib import Path
from typing import Iterable
from synthex_platform.core.archive import SynthexArchive
from .atomic_jsonl import JsonlLog


class JsonlArchiveStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.log = JsonlLog(self.path)

    def append(self, archive: SynthexArchive) -> None:
        self.append_unique(archive)

    def append_unique(self, archive: SynthexArchive) -> bool:
        return self.log.append(
            archive.model_dump(mode="json", exclude_none=True),
            identity=lambda row: row["metadata"]["archive_id"],
        )

    def iter_archives(self) -> Iterable[SynthexArchive]:
        for row in self.log.read_all():
            yield SynthexArchive.model_validate(row)

    def get(self, archive_id: str) -> SynthexArchive | None:
        for archive in self.iter_archives() or []:
            if archive.metadata.archive_id == archive_id:
                return archive
        return None

    def count(self) -> int:
        return sum(1 for _ in (self.iter_archives() or []))

    def rebuild_index(self) -> dict[str, int]:
        """Derived identity-to-ordinal index; the JSONL log stays authoritative."""
        index: dict[str, int] = {}
        for ordinal, archive in enumerate(self.iter_archives()):
            identifier = archive.metadata.archive_id
            if identifier in index:
                raise ValueError(f"duplicate historical archive_id: {identifier}")
            index[identifier] = ordinal
        return index

    def recover_trailing_partial(self) -> dict:
        return self.log.recover_trailing_partial()
