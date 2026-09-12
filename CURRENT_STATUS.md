# Synthex V3.4.2 Current Status

Synthex is being developed toward a materials-intelligence platform that links literature-derived synthesis/process information, structures/materials, experimental conditions, computational descriptors and measured performance with provenance.

## Mature / live paths

- Gas sensing: live structured extraction, normalization, validation and visualization foundation.
- Batteries: live domain routing and dedicated extraction, now expanded for true electrode-materials papers.

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
- PyPDF-first text extraction with a PyMuPDF fallback; OCR is not enabled.
- Low-variance Gemini settings (`temperature=0`, reproducibility seed `0`).

### Eight-document hardening result

- Routing: 8/8 correct; PDF ingestion: 8/8 (one PyMuPDF fallback).
- Six of six Gemini responses that were received passed strict validation and archive assembly.
- One in-domain document remains externally blocked by Gemini free-tier daily quota exhaustion.
- Canonical numeric records decreased from 115 unverified values to 55 admitted values; 140 candidates were retained in quarantine.
- The two review papers contributed zero canonical quantitative values after previously contributing 43 cited values.
- Full local suite: 60 passed, 2 warnings.
- Detailed comparison: `benchmark/outputs/corpus/after/scientific_admissibility_comparison.md`.

## Still platform scaffolds

Catalysis/electrocatalysis, corrosion, mechanical/creep/fatigue, additive manufacturing, photovoltaics, thermoelectrics, membranes, semiconductors and biomaterials have manifests/ontologies/benchmark roadmaps but are not yet at battery/gas-sensing live-validation maturity.

## V3.4 update — Serper enrichment

- Added optional Serper search-assisted mode after Gemini extraction.
- Serper is restricted to bibliographic metadata recovery and supplementary-information discovery.
- Search snippets cannot populate scientific measurements, synthesis conditions, compositions, or performance values.
- Added persistent local caching and a configurable local query budget (`SERPER_QUERY_BUDGET`, default 2500).
- Added retrieval provenance as a dedicated `retrieval` domain payload.
- Benchmark scripts remain paper-only with Serper disabled to prevent answer leakage.
- Added tests for caching, conservative metadata enrichment, and non-overwrite behavior.
