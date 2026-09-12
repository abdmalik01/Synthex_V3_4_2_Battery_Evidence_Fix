from __future__ import annotations

from synthex_platform.core.registry import DomainRegistry


def all_benchmarks(registry: DomainRegistry | None = None) -> list[dict]:
    registry = registry or DomainRegistry()
    rows = []
    for domain in registry.list_domains():
        for item in domain.get("benchmarks", []):
            rows.append({"domain": domain["slug"], **item})
    return rows


def benchmark_matrix(registry: DomainRegistry | None = None) -> dict[str, list[str]]:
    registry = registry or DomainRegistry()
    return {d["slug"]: [b["name"] for b in d.get("benchmarks", [])] for d in registry.list_domains()}
