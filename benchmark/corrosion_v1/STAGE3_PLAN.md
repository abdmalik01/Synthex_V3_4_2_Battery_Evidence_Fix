# Corrosion V1 — Stage 3 Benchmark Protocol

Status: **corpus locked; offline candidate bundle prepared; fixed A–H manual source review complete; offline gold-record regression verification pending before controlled live scoring**.

Current verified full repository regression baseline before the new gold-record regression test: **303 passed, 2 warnings**.

## Objective

Stage 3 measures whether the dedicated Corrosion V1 extraction path recovers paper-grounded corrosion data while preserving associations, source tracking, ownership, and scientific boundaries.

Stage 3 must not be used to weaken admission rules merely to improve a score.

## Fixed corpus

The fixed scored corpus contains eight roles defined in `corpus_manifest.json`:

1. CORR-GOLD-A — bare alloy / potentiodynamic polarization;
2. CORR-COAT-B — coating or surface treatment;
3. CORR-INHIB-C — inhibitor study;
4. CORR-EIS-D — EIS-heavy study;
5. CORR-WEIGHT-E — immersion / weight-loss study;
6. CORR-DFT-F — computational corrosion / adsorption study;
7. CORR-REVIEW-G — review contamination control;
8. CORR-NEGATIVE-H — non-corrosion routing control.

`CORR-HOLDOUT-I` is a ninth, unseen localized-corrosion paper. It is deliberately excluded from tuning and is used only after the fixed eight-paper benchmark has been hardened and frozen.

The nine PDFs are present in `benchmark/corrosion_v1/corpus pdfs/`. Exact filenames, expected DOI/title metadata, repository Git-blob hashes, and byte sizes are locked in `corpus_manifest.json`.

Run `benchmark/corrosion_v1/lock_corpus.py` locally before any live benchmark. The verifier makes zero external calls, computes SHA-256, checks repository blob hash and byte size, and checks that the expected DOI/title are present in PDF text. It writes `corpus_lock.json`.

`gold_candidates.json` remains an offline, zero-provider-call navigation bundle only. Its snippets are not gold.

## Gold annotation state and rules

Direct PDF review of the fixed A–H corpus is complete. Paper-level records live under `benchmark/corrosion_v1/gold/`; `gold_assertions_scaffold.json` tracks completion and points to those records. `CORR-HOLDOUT-I` has no tuning gold record.

For positive papers, scored observations are limited to values explicitly supported by the focal source and retain:

- reported property;
- printed value and unit;
- material association;
- experiment type;
- environment/test-condition association where necessary;
- reported reference electrode for potential quantities;
- source page and exact supporting evidence;
- ownership as focal work.

Do not pre-convert units, reference-electrode scales, corrosion rates, or normalization bases. Do not plot-digitize values into gold. Do not silently resolve contradictory source statements. Review/cited-prior-work values are never focal gold.

The gold records also preserve paper-specific safety decisions: the inhibitor-paper prose/table conflict is kept explicit; the weight-loss paper's condition ambiguity is not silently collapsed; the DFT paper remains computational; the review has zero focal experiments; and the LiFePO4 negative control must route to batteries.

## Score dimensions

`score_corrosion_archive` reports:

- **value accuracy** — correct property/value/unit without dimensional conversion;
- **association accuracy** — value attached to the correct experiment/material/reference-electrode context;
- **source-tracking coverage** — matched result retains paper, page, evidence snippet, and source origin;
- **recall** — required gold observations successfully associated;
- **overall** — mean of value accuracy, association accuracy, and source-tracking coverage.

The scorer deliberately does not award a match by converting units or electrode scales.

## Safety controls

Stage 3 also requires qualitative pass/fail checks:

- review/cited values do not enter canonical focal results;
- DFT outputs remain calculations;
- Rct/Rt, Rp, coating resistance and protective-layer resistance are not silently interchanged;
- corrosion/pitting/repassivation/breakdown potentials without a reported reference electrode are quarantined;
- unresolved condition conflicts remain unresolved;
- the negative control is not routed to corrosion merely because it contains generic electrochemistry or EIS terminology;
- the holdout paper is not used to tune prompts, validators, scoring rules, or thresholds.

## Run policy

Benchmark preparation and scorer tests are fully offline. Live Gemini extraction begins only after:

1. `lock_corpus.py` verifies the local corpus and writes `corpus_lock.json`;
2. the fixed A–H papers have manually verified gold assertions or explicit expected-rejection/routing contracts — **complete**;
3. offline scorer/corpus/gold-record tests pass — **pending local rerun after the latest gold-record commits**;
4. the full repository regression is green — last verified baseline **303 passed, 2 warnings**, rerun required after the latest test addition before claiming a new baseline.

Benchmark mode remains pinned: no credential failover and no silent model substitution during a scored run unless the benchmark contract is explicitly revised.

## Stage 3 exit gate

Stage 3 is complete only when the fixed eight-paper corpus has been run, every paper has an archived result or explicit expected rejection, score reports are saved, safety controls pass, the holdout remains untouched by tuning, and the full regression suite remains green.
