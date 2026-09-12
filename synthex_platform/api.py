from __future__ import annotations

import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query as ApiQuery

from synthex_platform.benchmarks import all_benchmarks
from synthex_platform.core.archive import SynthexArchive
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.interoperability import to_optimade_structures
from synthex_platform.query import Query, search
from synthex_platform.storage import JsonlArchiveStore

app = FastAPI(title="Synthex Materials Intelligence API", version="3.0.0")
registry = DomainRegistry()
store = JsonlArchiveStore(Path(os.getenv("SYNTHEX_ARCHIVE_PATH", "data/archive/archives.jsonl")))


@app.get("/v1/info")
def info():
    return {
        "name": "Synthex Materials Intelligence Platform",
        "version": "3.0.0",
        "domains": len(registry.list_domains()),
        "archive_entries": store.count(),
        "capabilities": ["literature extraction", "domain schemas", "provenance", "knowledge graph", "benchmarks", "OPTIMADE-like export"],
    }


@app.get("/v1/domains")
def domains():
    return registry.list_domains()


@app.get("/v1/domains/{slug}")
def domain(slug: str):
    try:
        return registry.get(slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/benchmarks")
def benchmarks():
    return all_benchmarks(registry)


@app.post("/v1/archives")
def create_archive(archive: SynthexArchive):
    if store.get(archive.metadata.archive_id):
        raise HTTPException(status_code=409, detail="archive_id already exists")
    store.append(archive)
    return {"archive_id": archive.metadata.archive_id, "status": "created"}


@app.get("/v1/archives/{archive_id}")
def get_archive(archive_id: str):
    archive = store.get(archive_id)
    if not archive:
        raise HTTPException(status_code=404, detail="Archive not found")
    return archive


@app.get("/v1/archives")
def query_archives(
    domain: str | None = None,
    element: str | None = None,
    formula_contains: str | None = None,
    property: str | None = None,
    target: str | None = None,
    year_min: int | None = ApiQuery(default=None, ge=1800, le=2200),
    year_max: int | None = ApiQuery(default=None, ge=1800, le=2200),
):
    result = search(store.iter_archives() or [], Query(
        domain=domain, element=element, formula_contains=formula_contains,
        property=property, target=target, year_min=year_min, year_max=year_max,
    ))
    return {"count": len(result), "data": result}


@app.get("/v1/optimade/structures")
def optimade_structures(domain: str | None = None):
    archives = store.iter_archives() or []
    if domain:
        archives = (a for a in archives if a.metadata.domain == domain)
    data = []
    for archive in archives:
        data.extend(to_optimade_structures(archive))
    return {"data": data, "meta": {"api_version": "1.x-compatible-export", "provider": "synthex"}}
