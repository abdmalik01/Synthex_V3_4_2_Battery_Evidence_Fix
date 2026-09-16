# Corrosion V1 — Stage 3 Benchmark Protocol

Status: **corpus locked; fixed A–H manual source review complete; controlled live scoring in progress; CORR-GOLD-A and CORR-COAT-B passed**.

Current verified full repository regression baseline remains **303 passed, 2 warnings**. Newer focused corrosion regressions have passed locally during Stage 3, but a newer repository-wide baseline must not be claimed until the full suite is rerun cleanly.

## Objective

Stage 3 measures whether the dedicated Corrosion V1 extraction path recovers paper-grounded corrosion data while preserving associations, source tracking, ownership, and scientific boundaries.

Stage 3 must not be used to weaken admission rules merely to improve a score.

## Live scoring progress

### CORR-GOLD-A — PASS

Controlled live run completed on 2026-09-16 after the record-level evidence-gate remediation.

- resolved route: `corrosion`; expected route: `corrosion`; route check passed;
- gold numeric assertions: 4/4 matched;
- recall: 100%;
- value accuracy: 100%;
- association accuracy: 100%;
- source-tracking coverage: 100%;
- overall score: 100%;
- canonical experiments: 4 EIS records;
- canonical metrics: 12;
- quarantine entries: 0;
- provider calls: 1 primary, 0 schema-repair;
- first response passed schema validation.

The successful rerun confirms that verified child metric/condition evidence can ground an experiment shell without weakening value-specific metric admission. The previous `no_verified_record_evidence` failure for the four EIS experiment records is closed for CORR-GOLD-A.

### CORR-COAT-B — PASS

Controlled live run completed on 2026-09-16 after strict recovery of exact native-page Table 1 evidence when the visual table detector missed the scientific table.

- resolved route: `corrosion`; expected route: `corrosion`; route check passed;
- gold numeric assertions: 5/5 matched after offline rescoring of the saved canonical archive;
- recall: 100%;
- value accuracy: 100%;
- association accuracy: 100%;
- source-tracking coverage: 100%;
- overall score: 100%;
- canonical experiments: 5 potentiodynamic-polarization records;
- canonical scored values: all 5 corrosion-current-density observations admitted with verified evidence;
- all 5 corrosion-potential values remained quarantined because the focal paper did not explicitly report the reference electrode;
- no coating resistance was relabelled as charge-transfer resistance;
- provider calls for the successful fresh extraction: 1 primary, 0 schema-repair;
- first response passed schema validation.

The initial 0/5 live score after evidence remediation was a benchmark association-normalization defect, not an extraction defect: the evidence-backed material name `20 # steel` did not match gold `20# steel`. The scorer now normalizes spacing around the material-grade hash marker without changing the global unit/experiment/reference normalization contract. The saved archive rescored offline at 5/5 without another provider call.

Next controlled live case: **CORR-INHIB-C**. Its preflight contract must preserve CSQN/NSQN treatment associations, method-specific inhibition efficiencies, the SCE reference electrode for the scored current-density rows, and the Table 2 association when nearby prose conflicts with the explicitly labelled table.

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
- treatment/inhibitor association where necessary;
- reported reference electrode for potential quantities and other gold rows whose identity depends on the stated electrochemical reference;
- source page and exact supporting evidence;
- ownership as focal work.

Do not pre-convert units, reference-electrode scales, corrosion rates, or normalization bases. Do not plot-digitize values into gold. Do not silently resolve contradictory source statements. Review/cited-prior-work values are never focal gold.

The gold records also preserve paper-specific safety decisions: the inhibitor-paper prose/table conflict is kept explicit; the weight-loss paper's condition ambiguity is not silently collapsed; the DFT paper remains computational; the review has zero focal experiments; and the LiFePO4 negative control must route to batteries.

## Score dimensions

`score_corrosion_archive` reports:

- **value accuracy** — correct property/value/unit without dimensional conversion; notation-only unit variants such as `μA/cm2` and `μA cm^-2` may be normalized without changing scale;
- **association accuracy** — value attached to the correct experiment/material/treatment/reference-electrode context required by gold;
- **source-tracking coverage** — matched result retains paper, page, evidence snippet, and source origin;
- **recall** — required gold observations successfully associated;
- **overall** — mean of value accuracy, association accuracy, and source-tracking coverage.

The scorer deliberately does not award a match by converting units or electrode scales. A long source-reported reference label may match its explicitly preserved parenthetical abbreviation, such as `saturated calomel electrode (SCE)` and `SCE`; this is textual identity handling, not electrode-scale conversion.

## Safety controls

Stage 3 also requires qualitative pass/fail checks:

- review/cited values do not enter canonical focal results;
- DFT outputs remain calculations;
- Rct/Rt, Rp, coating resistance and protective-layer resistance are not silently interchanged;
- corrosion/pitting/repassivation/breakdown potentials without a reported reference electrode are quarantined;
- inhibitor/coating efficiency values require a linked, admitted treatment;
- inhibitor-specific benchmark rows must remain associated with the correct inhibitor rather than receiving credit from a value alone;
- unresolved condition conflicts remain unresolved;
- the negative control is not routed to corrosion merely because it contains generic electrochemistry or EIS terminology;
- the holdout paper is not used to tune prompts, validators, scoring rules, or thresholds.

## Run policy

Benchmark preparation and scorer tests are fully offline. Before each next controlled live case:

1. `lock_corpus.py` verifies the local corpus and writes `corpus_lock.json`;
2. the fixed A–H papers retain manually verified gold assertions or explicit expected-rejection/routing contracts — **complete**;
3. focused offline corrosion scorer/corpus/gold/evidence/assembler tests must pass;
4. the full repository regression must be green before a new repository-wide baseline is claimed — last verified baseline **303 passed, 2 warnings**.

Benchmark mode remains pinned: no credential failover and no silent model substitution during a scored run unless the benchmark contract is explicitly revised.

## Stage 3 exit gate

Stage 3 is complete only when the fixed eight-paper corpus has been run, every paper has an archived result or explicit expected rejection, score reports are saved, safety controls pass, the holdout remains untouched by tuning, and the full regression suite remains green.
