# Catalysis / Electrocatalysis V1 Stage 3 benchmark

This is a controlled seven-paper, real-PDF benchmark for Catalysis V1. It measures routing, strict output validation, scientific association, provenance, ownership, and conservative canonical admission. It is not a broad literature benchmark.

## Methodology

- PDFs are the fixed local files under `corpus_pdfs/`; the benchmark never downloads substitutes.
- `gold/gold_a_heterogeneous_experimental.json` and `gold/gold_b_electrocatalysis.json` were independently curated from the authoritative PDFs, not from Synthex output.
- The former fictional “gold” scaffolds are isolated under `fixtures/templates/`, marked synthetic and non-scorable.
- Gold covers representative, difficult associations instead of every reported number.
- A numeric match counts only when its asserted catalyst, state, reaction, product, conditions, potential/reference, normalization basis, and duration also agree.
- Canonical precision is reported separately because false canonical admission is more harmful than unnecessary quarantine.

## Controlled roles

1. Gold A — heterogeneous CO2 methanation, catalyst variants, STY, and stability.
2. Gold B — Cu CO2RR co-electrolysis, product/potential/reference/basis associations, and DFT separation.
3. Computational DFT — HER/OER R-graphyne; calculations must not leak into experiments.
4. Stability/deactivation — high-entropy spinel CO oxidation.
5. Review contamination — cited and comparison-table values must remain non-focal.
6. Deferred photocatalysis — route to Catalysis but retain `deferred_subtype` scope.
7. Cross-domain negative control — ZnO/NiO gas sensing must route to `gas_sensing`.

## External-call policy

Offline tests and integrity checks make no Gemini, Serper, or web calls. A real benchmark extraction is an explicit controlled run through the normal pipeline with Serper disabled. Each initial Gemini request and the maximum one structured-output repair request are counted separately; persistent failures are recorded rather than retried until success.

## Scientific boundaries

Schema repair only makes a candidate `CatalysisDocument` structurally valid. It does not bypass Stage 2 evidence verification, ownership, normalization, conflict handling, quarantine, or assembly. Digitized graph values remain estimated, `not_submitted`, and noncanonical.

See `STAGE3_REPORT.md` for the final 39-point closure report and `outputs/stage3_run_summary.json` for the machine-readable final result set. `outputs/execution_ledger.json` records superseded development runs and transport/provider failures transparently.
