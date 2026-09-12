from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml


class DomainRegistry:
    def __init__(self, manifest_dir: str | Path | None = None):
        self.manifest_dir = Path(manifest_dir or Path(__file__).parents[1] / "domains" / "manifests")
        self._domains: dict[str, dict[str, Any]] = {}
        self.reload()

    def reload(self) -> None:
        self._domains.clear()
        for path in sorted(self.manifest_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            slug = data["slug"]
            if slug in self._domains:
                raise ValueError(f"Duplicate domain slug: {slug}")
            self._domains[slug] = data

    def list_domains(self) -> list[dict[str, Any]]:
        return [self._domains[k] for k in sorted(self._domains)]

    def get(self, slug: str) -> dict[str, Any]:
        if slug not in self._domains:
            raise KeyError(f"Unknown Synthex domain: {slug}")
        return self._domains[slug]

    def property_catalog(self, slug: str) -> list[dict[str, Any]]:
        return self.get(slug).get("properties", [])

    def benchmark_catalog(self, slug: str) -> list[dict[str, Any]]:
        return self.get(slug).get("benchmarks", [])
