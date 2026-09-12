from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable
from synthex_platform.core.archive import SynthexArchive


class JsonlArchiveStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, archive: SynthexArchive) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(archive.model_dump_json(exclude_none=True) + "\n")

    def iter_archives(self) -> Iterable[SynthexArchive]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield SynthexArchive.model_validate_json(line)

    def get(self, archive_id: str) -> SynthexArchive | None:
        for archive in self.iter_archives() or []:
            if archive.metadata.archive_id == archive_id:
                return archive
        return None

    def count(self) -> int:
        return sum(1 for _ in (self.iter_archives() or []))
