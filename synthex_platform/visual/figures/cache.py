"""Caller-owned cache for optional figure-understanding provider results."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

from synthex_platform.core.identifiers import stable_id
from synthex_platform.visual.models import FigureUnderstandingResult


class FigureUnderstandingCache:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def key(self, source_checksum: str, figure_id: str, provider: str, model: str, schema_version: str) -> str:
        return stable_id("figcache", source_checksum, figure_id, provider, model, schema_version)

    def get(self, key: str) -> FigureUnderstandingResult | None:
        path = self.directory / f"{key}.json"
        return FigureUnderstandingResult.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def put(self, key: str, result: FigureUnderstandingResult) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"{key}.json"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=self.directory, suffix=".tmp") as handle:
            handle.write(result.model_dump_json(exclude_none=True, indent=2))
            temporary = Path(handle.name)
        try:
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return target
