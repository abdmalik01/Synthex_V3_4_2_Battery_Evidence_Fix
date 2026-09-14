# Synthex V3.4.2 Current Status

Synthex is being developed toward a materials-intelligence platform that links literature-derived synthesis/process information, structures/materials, experimental conditions, computational descriptors and measured performance with provenance.

## Mature / live paths

- Gas sensing: live structured extraction, normalization, validation and visualization foundation.
- Batteries: live domain routing and dedicated extraction, now expanded for true electrode-materials papers.
- Paper Discovery V1: live primary-platform Serper discovery workspace with cached/budgeted search, explicit unverified discovery candidates and session-only saved bibliography leads. Discovery requires a later real-PDF upload before SourceBundle-based scientific extraction.
- CSV Export V1: complete deterministic researcher-facing results CSV and relational CSV bundle derived from validated archives. Canonical rows are the default; quarantined rows require explicit opt-in and remain visibly identified. JSON remains canonical.
- Archive Explorer V1: complete read-only session-archive browser with a researcher-friendly Results table, local search and archive-derived filters, explicit quarantine opt-in, separate entity/calculation/evidence/relationship views, source tracking, and filtered CSV download.
- **Synthex Research UI V1 — COMPLETE:** the primary Streamlit app now opens on a focused researcher home, follows Analyze → Review → Explore → Export, presents archive-only summaries and result highlights, translates trust status without hiding exact machine fields, and groups specialist tools under Advanced navigation.
- **LLM Provider Resilience V1 — COMPLETE:** production extraction uses an ordered Gemini fallback chain with one bounded attempt per model for availability-class failures only. Benchmarks remain single-model pinned; repair calls stay on the selected model; request audit metadata records model selection and redacted failure classes.
- **Visual Intelligence V1 — COMPLETE:** native table extraction, visual provenance and sidecars, figure understanding, generated tables/charts, OCR fallback, and calibrated graph digitization.

## CSV Export V1 guarantees

- Export uses the already-built `SynthexArchive`; it does not rerun extraction or call Gemini, Serper, or the web.
- `results.csv` contains canonical/admitted measurements by default; `results_all.csv` is an explicit quarantine-inclusive view.
- Trust columns preserve ownership, admission status, evidence origin, evidence strength, estimated status, rejection reason, and audit path where applicable.
- Relational tables preserve stable join IDs and keep calculations/DFT separate from experiments.
- UTF-8 BOM, scientific Unicode, deterministic ordering/JSON-in-cell encoding, blank missing values, and formula-injection protection support safe spreadsheet use.
- CSV is a derived research view only; archive JSON remains the canonical data model.

## Archive Explorer V1 guarantees

- The Explorer reads the validated archive already held in Streamlit session state and never reparses the PDF or calls an external provider.
- Its Results view reuses the CSV Export V1 observation projection so the UI and downloaded data agree.
- Canonical/admitted observations are the default. Quarantined rows require an explicit toggle and retain visible rejection and trust fields.
- Domain, source, material, experiment type, reaction, metric, product, admission, ownership, evidence-origin, estimated, and local text filters are offered only from loaded archive values.
- Materials, processes, experiments, calculations, evidence, and relationships remain distinct, with clean empty states.
- Result selection exposes concise source tracking without displaying the paper's full text.

## Visual Intelligence V1 scientific guarantees

- Visual extraction products do not automatically create canonical measurements.
- OCR is explicitly marked `origin="ocr_extracted"` and remains distinguishable from native extraction.
- Digitized graph points are always `origin="figure_digitized"`, `estimated=true`, and `evidence_strength="estimated_digitized"`.
- Digitized values remain visual sidecar products outside canonical admission by default.
- Uncertainty, calibration, raw pixel coordinates, warnings, and rejection reasons are retained for audit.
- Batteries V1 remains frozen; Visual Intelligence does not alter its schemas or archive-admission rules.

## Batteries V1.3 scientific-admissibility additions

- Research-grade material + synthesis schema.
- Electrode fabrication and cell assembly records.
- Electrochemical test protocol records.
- Shared protocol references and deterministic de-duplication.
- Subtype-aware completeness scoring.
- Evidence-aware provenance scoring.
- Unit normalization coverage.
- 19-file validation corpus manifest (17 unique; 15 battery-relevant; 2 negative controls).
- Li2FeTiO4 electrode-materials gold benchmark and live benchmark runner.
- Focal/cited/background ownership classification for extracted scientific results.
- Deterministic normalized-verbatim evidence verification and quantitative archive gate.
- Quarantine audit for values that lack focal ownership or verified provenance.
- Structured experimental-condition conflicts with unresolved disputed values removed.
- Battery DFT outputs assembled as calculations rather than cycling experiments.
- Internal archive and battery material/protocol reference validation.
- PyPDF-first text extraction with a PyMuPDF fallback and an opt-in, explicitly labelled Tesseract OCR fallback for insufficient pages.
- Low-variance Gemini settings (`temperature=0`, reproducibility seed `0`).

### Eight-document hardening result

- Routing: 8/8 correct; PDF ingestion: 8/8 (one PyMuPDF fallback).
- Six of six Gemini responses that were received passed strict validation and archive assembly.
- One in-domain document remains externally blocked by Gemini free-tier daily quota exhaustion.
- Canonical numeric records decreased from 115 unverified values to 55 admitted values; 140 candidates were retained in quarantine.
- The two review papers contributed zero canonical quantitative values after previously contributing 43 cited values.
- Full local suite: 60 passed, 2 warnings.
- Detailed comparison: `benchmark/outputs/corpus/after/scientific_admissibility_comparison.md`.

## Catalysis / Electrocatalysis status

Stages 1–3 are implemented. The fixed seven-paper Stage 3 benchmark is historically complete with
its strict schema, routing, evidence, ownership, admission, and safety acceptance targets intact.
The bounded follow-up did not close the demonstrated Gold A completeness and Gold B association
gaps. Catalysis is therefore **not frozen and not ready for Stage 4**; Stage 4 has not begun.

## Still platform scaffolds

Corrosion, mechanical/creep/fatigue, additive manufacturing, photovoltaics, thermoelectrics, membranes, semiconductors and biomaterials have manifests/ontologies/benchmark roadmaps but are not yet at battery/gas-sensing live-validation maturity.

## V3.4 update — Serper enrichment

- Added optional Serper search-assisted mode after Gemini extraction.
- Serper is restricted to bibliographic metadata recovery and supplementary-information discovery.
- Search snippets cannot populate scientific measurements, synthesis conditions, compositions, or performance values.
- Added persistent local caching and a configurable local query budget (`SERPER_QUERY_BUDGET`, default 2500).
- Added retrieval provenance as a dedicated `retrieval` domain payload.
- Benchmark scripts remain paper-only with Serper disabled to prevent answer leakage.
- Added tests for caching, conservative metadata enrichment, and non-overwrite behavior.

## Paper Discovery V1 boundary

- **Discover Papers** is a researcher workflow for finding and opening paper links; it is not an extraction workflow.
- Search snippets, titles, URLs and saved discovery metadata are never canonical scientific evidence and cannot create archive records, `SourceBundle`s, materials, experiments, measurements or calculations.
- The researcher must obtain and upload the actual PDF. Its `SourceBundle`, routing, extraction, evidence verification, admission and quarantine controls remain authoritative.
- Arbitrary server-side result-URL downloads are deliberately unsupported because of SSRF, redirect, content-size, publisher-access, licensing and provenance risks.
