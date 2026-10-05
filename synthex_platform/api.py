from __future__ import annotations

import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query as ApiQuery
from pydantic import BaseModel

from synthex_platform.benchmarks import all_benchmarks
from synthex_platform.core.archive import SynthexArchive
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction import DomainRouter, SynthexExtractionPipeline
from synthex_platform.interoperability import to_optimade_structures
from synthex_platform.live_jobs import JobAlreadyRunning, LiveExtractionService
from synthex_platform.query import Query, search
from synthex_platform.storage import JsonlArchiveStore
from synthex_platform.storage.atomic_jsonl import CorruptJsonlError
from synthex_platform.system_status import SystemAuditReader

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


@app.get("/v1/system/status")
def system_status():
    return SystemAuditReader().status()


@app.get("/v1/system/benchmarks")
def system_benchmarks(domain: str | None = None):
    return SystemAuditReader().benchmarks(domain)


@app.get("/v1/system/benchmarks/{domain}")
def system_benchmarks_domain(domain: str):
    return SystemAuditReader().benchmarks(domain)


@app.get("/v1/system/provider-runs")
def system_provider_runs(domain: str | None = None):
    return SystemAuditReader().provider_runs(domain)


@app.get("/v1/system/safety")
def system_safety():
    return SystemAuditReader().safety()


@app.get("/v1/system/jobs")
def system_jobs():
    return SystemAuditReader().jobs()


@app.get("/v1/system/jobs/{job_id}")
def system_job(job_id: str):
    job = SystemAuditReader().job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


class OperatorResumeRequest(BaseModel):
    action_id: str
    reason: str = "operator_requested"


class OperatorReconcileRequest(BaseModel):
    action_id: str
    decision: str
    reason: str
    external_action_id: str
    expected_request_hash: str
    expected_source_id: str
    expected_model: str | None = None
    artifact_ref: str | None = None


def _operator_service() -> LiveExtractionService:
    if os.getenv("SYNTHEX_OPERATOR_API_ENABLED", "false").casefold() != "true":
        raise HTTPException(status_code=403, detail="Operator API is disabled")
    root = Path(os.getenv("SYNTHEX_JOB_LOG_PATH", "data/jobs/events.jsonl")).parent
    return LiveExtractionService(root=root, archive_store=store)


def _operator_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="Job not found")
    if isinstance(exc, JobAlreadyRunning):
        return HTTPException(status_code=409, detail="Job already has a local executor")
    return HTTPException(status_code=409, detail="Operator action rejected by state or identity precondition")


@app.post("/v1/jobs/{job_id}/resume")
def resume_job(job_id: str, request: OperatorResumeRequest):
    service = _operator_service()
    try:
        pipeline = SynthexExtractionPipeline(router=DomainRouter(registry))
        outcome = service.resume_safe(job_id, action_id=request.action_id,
                                      reason=request.reason, pipeline=pipeline)
        return {"job": SystemAuditReader(jobs=service.jobs).job(job_id),
                "resumed": outcome is not None}
    except (KeyError, ValueError, RuntimeError, OSError) as exc:
        raise _operator_error(exc) from exc


@app.post("/v1/jobs/{job_id}/reconcile")
def reconcile_job(job_id: str, request: OperatorReconcileRequest):
    service = _operator_service()
    try:
        service.reconcile(job_id, **request.model_dump())
        return {"job": SystemAuditReader(jobs=service.jobs).job(job_id)}
    except (KeyError, ValueError, RuntimeError, OSError) as exc:
        raise _operator_error(exc) from exc


@app.post("/v1/jobs/{job_id}/abandon")
def abandon_job(job_id: str, request: OperatorReconcileRequest):
    if request.decision != "ABANDON":
        raise HTTPException(status_code=422, detail="Abandon endpoint requires ABANDON decision")
    return reconcile_job(job_id, request)


@app.post("/v1/archives")
def create_archive(archive: SynthexArchive):
    try:
        if not store.append_unique(archive):
            raise HTTPException(status_code=409, detail="archive_id already exists")
    except CorruptJsonlError as exc:
        raise HTTPException(status_code=503, detail="Archive storage requires explicit recovery") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
