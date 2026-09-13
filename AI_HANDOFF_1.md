# AI Handoff 1 — Synthex V3.4.2

Read this file before changing Synthex. It records the completed work through commit `1171ce2` on 2026-09-13.

## Repository state

- Current implementation commit: `1171ce2` — `Restore safe paper discovery workflow`.
- The latest full test run passed: **149 passed, 2 warnings**.
- The two warnings are pre-existing: a `google-genai` Python 3.17 deprecation warning and pytest collection of `TestingConditions`.
- Do not commit or delete the existing `.pytest_*` directories or generated `data/archive/visual/...` sidecars without explicit direction. They are local/runtime artifacts, not implementation work.
- `CODEX_HANDOFF.md` is older context and is partly stale. In particular, it predates Catalysis V1 Stage 1/2 and the Paper Discovery restoration. Prefer this handoff, `CURRENT_STATUS.md`, and recent Git history.

## Product architecture

Synthex has two active application layers:

```text
Legacy Gas Sensing V2
  streamlit_app.py / main.py / synthex_v2/

Synthex V3 platform
  platform_app.py / platform_cli.py / synthex_platform/
  PDF → SourceBundle → router → domain extractor → validation/assembly
      → SynthexArchive → storage/query/analytics/graph/API
```

The platform uses typed records for sources, materials, processes, devices, experiments, calculations, relationships, domain payloads, quality, and evidence. The canonical archive is `SynthexArchive`.

## Completed milestones

### Batteries V1 — frozen

Battery extraction has dedicated models, normalization, assembly, benchmark fixtures and strict scientific admission. It supports materials, synthesis, electrode fabrication, cell assembly, testing, performance and DFT/calculation records.

### Visual Intelligence V1 — complete and frozen

Implemented capabilities:

- native table extraction;
- provenance sidecars;
- figure understanding;
- generated analytics/charts;
- explicit Tesseract OCR fallback;
- calibrated graph digitization.

Visual outputs are not a canonical-admission route by default. OCR has explicit `origin="ocr_extracted"`; digitized values have `origin="figure_digitized"`, `estimated=true`, uncertainty/rejection metadata and remain outside canonical admission.

### Generic routing and ownership hardening — complete

Materials-informatics/data-descriptor papers such as MatKG use a safe generic fallback rather than being misrouted to Catalysis because of incidental terms. Generic entities carry ownership (`focal_work`, `cited_prior_work`, `review_summary`, `comparison_table`, `background`, `example`, `unknown`), and non-focal objects remain in payload/quarantine rather than becoming canonical records.

### Catalysis / Electrocatalysis V1 — Stage 1 and Stage 2 implemented

Dedicated catalysis models, routing, extraction, normalization, evidence verification, assembly and quarantine/admission exist under `synthex_platform/extraction/catalysis_*.py`. Do not broaden it into a new stage unless asked. `CURRENT_STATUS.md` still has stale scaffold wording for Catalysis; inspect code/tests before relying on that sentence.

### Structured-output recovery — complete

The generic extractor accepts a top-level JSON object or a singleton list containing exactly one object. Empty/multi-item lists and primitive JSON fail clearly. Strict Pydantic schemas remain in force.

Known safe recovery behavior:

- pipeline-owned `source_id`, `filename`, and `source_checksum` can be allowlisted, checked against `SourceBundle`, stripped before strict validation, and reattached authoritatively;
- all other unknown scientific fields remain invalid;
- nested condition evidence strings are normalized only when deterministic source text/provenance supports a valid `Evidence` object;
- unsupported evidence remains invalid and follows the bounded repair path.

### Paper Discovery V1 — complete

`platform_app.py` now has **Discover Papers**. It is a primary V3 workspace, not another app.

```text
Discover Papers
  → Serper discovery metadata only
  → researcher opens a result externally and obtains the paper
  → researcher uploads the actual PDF
  → SourceBundle → routing → extraction → evidence verification → admission/quarantine
```

Implementation:

- `synthex_platform/retrieval/discovery.py`: typed `DiscoveryCandidate` and `DiscoverySearchResult`, query construction, parsing, safe user-facing error mapping, and session-state helpers.
- `platform_app.py`: query form, result cards, cache/budget information, external links, session-persistent results, and session-only “Save for extraction” candidates.
- `tests/test_paper_discovery.py`: offline mocked tests.

Paper Discovery invariants:

- snippets, titles, URLs and selected candidate metadata are **not scientific evidence**;
- they cannot create `Evidence`, `SourceBundle`, `SynthexArchive`, material, experiment or measurement records;
- results may be opened externally only;
- no arbitrary `requests.get(result_url)` server-side downloader exists or should be restored;
- selected metadata is display-only on Extract Paper and is not automatically applied to the uploaded PDF;
- direct DOI URLs may display DOI metadata; authors, journal, publisher and weakly inferred years are not invented;
- Serper is still cached/budgeted through `SerperClient` and no API keys are displayed.

## Non-negotiable scientific rules

1. Do not weaken Pydantic validation or `extra="forbid"` to make model output pass.
2. Do not invent scientific values, conditions, provenance, page locations, identities or ownership.
3. Preserve raw and normalized values separately.
4. Canonical admission requires focal ownership and sufficiently verified source evidence where the domain gate requires it.
5. Retain rejected/non-admitted values in quarantine/audit structures; do not silently discard them.
6. Search snippets are for discovery/bibliographic enrichment only, never scientific measurements or evidence.
7. Visual OCR and digitized figures remain explicitly labelled and non-canonical by default.
8. Do not modify Batteries V1 or Visual Intelligence V1 without an explicit request.

## Key entry points

| Purpose | File / command |
|---|---|
| Main V3 Streamlit UI | `streamlit run platform_app.py` |
| Legacy Gas Sensing V2 UI | `streamlit run streamlit_app.py` |
| V3 extraction front door | `synthex_platform/extraction/pipeline.py` |
| Generic extractor/recovery | `synthex_platform/extraction/domain_extractor.py` |
| Domain router | `synthex_platform/extraction/router.py` |
| Source/PDF/OCR context | `synthex_platform/extraction/source_context.py` |
| Serper client | `synthex_platform/retrieval/serper_client.py` |
| Metadata enrichment | `synthex_platform/retrieval/metadata_enricher.py` |
| Paper Discovery | `synthex_platform/retrieval/discovery.py` |
| Canonical models | `synthex_platform/core/models.py`, `core/archive.py` |
| Local archive storage/query | `storage/jsonl_store.py`, `query/local.py` |
| API | `synthex_platform/api.py` |

## Environment and test guidance

Required local secrets are kept in `.env` and must never be committed:

```env
GEMINI_API_KEY=...
GEMINI_MODEL=...
SERPER_API_KEY=...
SERPER_QUERY_BUDGET=2500
```

Tesseract is installed locally at:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

The project `.venv\Scripts\python.exe` runs tests correctly. The Streamlit launcher has shown a linkage to an older V3.4 environment and Windows console-encoding errors in `streamlit docs`; do not change environment files automatically. Diagnose interpreter/launcher consistency before changing dependencies.

Run tests with a new disposable temporary base directory, never tracked `.pytest_tmp`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp "$env:TEMP\synthex_<task_name>"
```

## Deliberately deferred work

- Do not restore legacy FAISS/RAG without a measured benchmark proving safe retrieval improves extraction.
- Do not build universal V3 batch ingestion, a V3 extraction CLI, enhanced archive filtering UI, or a visual-sidecar browser unless requested.
- Do not restore direct server-side result-URL downloads; they create SSRF, redirect, content-size, malicious-file, licensing and provenance risks.
- Do not begin a new Catalysis stage or new scientific vertical automatically.

## Suggested first actions for a future AI

1. Read this file, `README.md`, `CURRENT_STATUS.md`, `ARCHITECTURE_V3.md`, and recent Git history.
2. Inspect `git status --short` before editing; preserve local/generated artifacts unless explicitly asked to clean them.
3. Read the relevant domain models, assembler, extractor and tests before changing behavior.
4. Make narrowly scoped changes that preserve the scientific rules above.
5. Run focused tests, then the full suite using a disposable pytest base directory.
