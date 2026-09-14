# Synthex V3.4.2 — Materials Intelligence Platform

Synthex is evolving from a nanomaterial parameter extractor into a literature-to-materials-data platform. It preserves the mature gas-sensing V2 workflow, adds automatic scientific-domain routing, and now includes a dedicated Batteries V1 extraction path that writes into a shared provenance-aware Synthex Archive.

## Current scientific maturity

- **Gas sensing:** mature V2 vertical — synthesis/deposition + sensing performance + validation + visualizations.
- **Batteries:** live V1 expansion — auto-routing, battery paper typing, charge/discharge/EIS protocol extraction, battery IDs/condition groups, performance points, universal archive assembly.
- **Catalysis/electrocatalysis:** Stages 1–3 are implemented and the controlled seven-paper Stage 3 benchmark is historically complete. Its strict validation and safety gates pass, but demonstrated Gold A recall and Gold B association gaps remain; Stage 4/freeze has not begun.
- **Corrosion, mechanical/creep/fatigue, additive manufacturing, photovoltaics, thermoelectrics, membranes, semiconductors, biomaterials:** domain manifests, canonical properties and benchmark tasks exist; these remain generic/scaffold extractors.

See `CURRENT_STATUS.md` for the plain-language project status.
Visual Intelligence V1 is complete: native tables, provenance sidecars, figure understanding, generated charts, explicit OCR fallback, and calibrated graph digitization. These visual products remain outside canonical admission by default; see `docs/VISUAL_INTELLIGENCE_V1_STATUS.md`.

## Run the platform dashboard

```bash
pip install -r requirements.txt
streamlit run platform_app.py
```

Use **Analyze Paper → Auto Detect** to route an uploaded PDF. Battery and catalysis papers are sent to their dedicated extractors.

The primary UI is organized around the researcher workflow: **Home**, **Analyze Paper**,
**Discover Papers**, **Explore Results**, and **Visualize Data**. Validation catalogs,
figure digitization, diagnostics, registry data, graph export, and the legacy gas-sensing
entry point remain available under clearly labelled **Advanced** navigation.

## Paper discovery → PDF extraction boundary

Use **Discover Papers** in `platform_app.py` to search with Serper, open a result externally, and optionally save its unverified bibliographic metadata for a later upload. Discovery results contain navigation metadata only: title, URL, provider snippet, cache/query provenance and a DOI only when it is directly present in a DOI URL.

```text
Discover Papers
    → discovery only; search snippets are never scientific evidence

Upload PDF
    → SourceBundle → extraction → evidence verification → admission/quarantine
```

Synthex never fetches arbitrary result URLs server-side and never creates an archive, `SourceBundle`, material, measurement, or experiment from a title, URL, or search snippet. An actual uploaded PDF remains authoritative.

## Quick routing test — no Gemini request

```bash
python smoke_route.py "path/to/paper.pdf"
```

## Battery live extraction test

```bash
python smoke_battery.py "path/to/battery_paper.pdf"
```

Requires a root `.env` file containing:

```env
GEMINI_API_KEY=your_real_key
GEMINI_MODEL=gemini-3.8-flash
GEMINI_FALLBACK_MODELS=gemini-3.5-flash,gemini-3.6-flash,gemini-3.7-flash
```

The `.env` file is ignored by Git. Do not place real keys in `.env.example`.

Production extraction uses a shared, bounded Gemini gateway. It tries the preferred model and
then the configured fallback models once each only for provider/model availability, timeout, or
transport failures. Authentication, quota, safety, unexpected, schema-validation, and scientific
validation failures do not trigger cross-model retries. Benchmark runners are explicitly pinned to
one model, and any schema-repair request stays on the model that produced the primary output.
Every request records requested/actual model and attempt/failure metadata without API keys.

Battery extraction uses `temperature=0` and reproducibility seed `0`. PyPDF remains the primary text parser; PyMuPDF is a non-OCR fallback for
structurally valid PDFs that PyPDF cannot decode. Quantitative values remain in the raw
battery payload, but the canonical archive admits only focal-work values backed by a
normalized verbatim evidence match. Other values are retained in the payload's
`admissibility.quarantine` audit with semantic warnings.

## Existing gas-sensing application

```bash
streamlit run streamlit_app.py
```

## API

```bash
uvicorn synthex_platform.api:app --reload
```

## Tests

```bash
pytest -q
```

## Platform outputs

- `data/archive/archives.jsonl` — append-only local research archive
- `data/graph/nodes.jsonl` + `edges.jsonl` — derived knowledge graph
- `catalog/domain_catalog.json` — domain registry
- `catalog/benchmark_catalog.json` — benchmark roadmap
- `schemas/synthex_archive.schema.json` — canonical archive schema

### Researcher CSV exports

After an extraction finishes, **Analyze Paper → Export Results** provides **Download JSON**,
**Download CSV**, and **Download CSV Bundle**. JSON remains canonical; CSV is a deterministic
derived view of that already-built archive and does not re-run Gemini or extraction.

`results.csv` contains canonical/admitted measurements only. Researchers can explicitly enable
quarantined rows to receive `results_all.csv`, where every such row is visibly marked with its
admission status, ownership, rejection reason, and audit path. The relational ZIP separates
sources, materials, processes, experiments, calculations, measurements, relationships, and
evidence using stable join IDs. Files are UTF-8 with BOM for Windows spreadsheet compatibility,
preserve scientific symbols and approximate raw values, and escape formula-like text safely.
See `docs/CSV_EXPORT_V1.md` for the full contract.

### Explore Results

**Explore Results** lets researchers browse and filter the structured information Synthex
extracted from the current paper without reading archive JSON. It uses the already-built session
archive and performs only local, deterministic filtering. Opening the Explorer never re-runs PDF
parsing or calls Gemini, Serper, embeddings, or the web.

The default Results view shows canonical observations. **Include quarantined** is an explicit
option; included records remain visibly marked with their ownership, admission status, and
rejection reason. Materials, processes, experiments, calculations, evidence, and relationships
have separate views. Selecting a result reveals source tracking: title, DOI, page, exact evidence
snippet, evidence origin/strength, ownership, admission status, and estimated status. The current
filtered result set can be downloaded as CSV without changing the archive.

Researcher-facing trust labels (`Verified`, `Admitted`, `Estimated`, `Needs review`) summarize—but
never replace—the exact machine admission, ownership, evidence, uncertainty, and quarantine fields.
Paper summaries and result highlights are deterministic projections of the validated archive; they
do not invoke an LLM or invent scientific conclusions.

The long-term goal is research usefulness comparable to large materials-data infrastructures, with Synthex differentiated by linking literature-derived **processing → structure/material → computation → experimental conditions → performance** with explicit provenance.

## V3.4: optional Serper search-assisted enrichment

Synthex can now use Serper alongside Gemini without treating search snippets as scientific truth.

- Gemini remains the PDF scientific extractor.
- Serper is optional and is used only for missing bibliographic metadata and discovery of supplementary/supporting information.
- Scientific measurements, synthesis conditions, composition and performance values are never populated from search snippets.
- Search results are cached under `data/search_cache/`, so identical queries do not consume another network query.
- A local query counter respects `SERPER_QUERY_BUDGET` (default `2500`). This is a local safety budget, not a replacement for your Serper account dashboard.
- Benchmark scripts remain **paper-only**; Serper is intentionally off during benchmark scoring.

Add to `.env`:

```env
SERPER_API_KEY=your_key_here
SERPER_QUERY_BUDGET=2500
```

Run the platform UI:

```powershell
streamlit run platform_app.py
```

Then enable **Search-assisted enrichment with Serper** only when you want metadata/supplementary discovery.

**Discover Papers** is the separate researcher-facing search workflow. It preserves results in the current Streamlit session until a new search or explicit clear action. Saved discovery candidates remain session-only bibliography leads and are not canonical archive data.
