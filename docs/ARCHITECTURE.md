# Synthex architecture

Synthex has a research UI (`platform_app.py`), a FastAPI surface
(`synthex_platform/api.py`), and an offline benchmark/audit layer. The API and
UI share the same core models; neither may turn a search snippet or unverified
provider text into an admitted scientific measurement.

```text
uploaded PDF → SourceBundle / source tracking → domain router
            → deterministic recovery and/or configured provider adapter
            → typed draft → evidence + ownership checks → admission/quarantine
            → SynthexArchive → JSONL archive → analytics/graph/exports
                                      ↘ durable job journal / operator audit
locked benchmark source + gold → offline closure → frozen-scope manifest
persisted provider response      → offline replay/score → separate live gate
```

| Boundary | Implementation | Invariant |
| --- | --- | --- |
| Intake and routing | `source_store.py`, `extraction/router.py`, `extraction/pipeline.py` | Source identity and detected domain travel with the record. |
| Provider abstraction | `providers/contracts.py`, `providers/gemini_adapter.py`, `providers/gemini_gateway.py` | Explicit configuration, bounded attempts, exact-model benchmark runs; no gold in requests. |
| Domain contracts | `domains/manifests/`, `extraction/*_contract.py` | Draft schema and scientific meaning are domain-specific. |
| Validation/admission | `extraction/assembler.py`, evidence modules, `core/models.py` | Focal ownership and source evidence are required; uncertain content is quarantined. |
| Persistence | `storage/atomic_jsonl.py`, `storage/jsonl_store.py`, `jobs.py`, `live_jobs.py` | Archive and job events are append-only/durable; uncertain external actions require reconciliation. |
| Derived views | `export/`, `graph/`, `explorer/`, `system_status.py` | Read-only projection cannot upgrade scientific status or expose local paths/secrets. |
| Benchmarks | `benchmark/<domain>_v1/` | Source/gold locks and frozen manifests are independent from provider availability. |

The ten-domain system audit is a projection of precomputed benchmark artifacts,
not a live provider health check. Gas-sensing V2 is a separate legacy vertical.
Biomaterials is deterministically closed in the current audit but not frozen;
its live gate is pending. Never use a dashboard badge as a substitute for a
source/gold hash or freeze-manifest check.

`synthex_v2/`, `tests/`, and the older root-level smoke scripts remain for
compatibility. Do not move them into `synthex_platform/` without import,
archive, CLI, and benchmark-reference migration tests.
