# Synthex V3.4.2 — Materials Intelligence Platform

Synthex is evolving from a nanomaterial parameter extractor into a literature-to-materials-data platform. It preserves the mature gas-sensing V2 workflow, adds automatic scientific-domain routing, and now includes a dedicated Batteries V1 extraction path that writes into a shared provenance-aware Synthex Archive.

## Current scientific maturity

- **Gas sensing:** mature V2 vertical — synthesis/deposition + sensing performance + validation + visualizations.
- **Batteries:** live V1 expansion — auto-routing, battery paper typing, charge/discharge/EIS protocol extraction, battery IDs/condition groups, performance points, universal archive assembly.
- **Catalysis, corrosion, mechanical/creep/fatigue, additive manufacturing, photovoltaics, thermoelectrics, membranes, semiconductors, biomaterials:** domain manifests, canonical properties and benchmark tasks exist; these remain generic/scaffold extractors until domain-specific benchmarking is completed.

See `CURRENT_STATUS.md` for the plain-language project status.
Visual Intelligence V1 is complete: native tables, provenance sidecars, figure understanding, generated charts, explicit OCR fallback, and calibrated graph digitization. These visual products remain outside canonical admission by default; see `docs/VISUAL_INTELLIGENCE_V1_STATUS.md`.

## Run the platform dashboard

```bash
pip install -r requirements.txt
streamlit run platform_app.py
```

Use **Extract Paper → Auto Detect** to route an uploaded PDF. Battery papers are sent to the dedicated Batteries V1 extractor.

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
```

The `.env` file is ignored by Git. Do not place real keys in `.env.example`.

Battery extraction uses `temperature=0` and reproducibility seed `0` with the configured
Gemini model. PyPDF remains the primary text parser; PyMuPDF is a non-OCR fallback for
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
