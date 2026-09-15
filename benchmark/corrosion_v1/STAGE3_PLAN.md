# Corrosion V1 — Stage 3 Benchmark Protocol

Status: **benchmark infrastructure implemented; real-paper corpus selection and gold annotation pending**.

## Objective

Stage 3 measures whether the dedicated Corrosion V1 extraction path recovers paper-grounded corrosion data while preserving associations, source tracking, ownership, and scientific boundaries.

Stage 3 must not be used to weaken admission rules merely to improve a score.

## Fixed corpus

The corpus is frozen at eight roles defined in `corpus_manifest.json`:

1. CORR-GOLD-A — bare alloy / potentiodynamic polarization;
2. CORR-COAT-B — coating or surface treatment;
3. CORR-INHIB-C — inhibitor study;
4. CORR-EIS-D — EIS-heavy study;
5. CORR-WEIGHT-E — immersion / weight-loss study;
6. CORR-DFT-F — computational corrosion / adsorption study;
7. CORR-REVIEW-G — review contamination control;
8. CORR-NEGATIVE-H — non-corrosion routing control.

No paper is admitted to the fixed corpus until the PDF is locally available and a human can verify the gold assertions directly from the source. DOI/title metadata alone is not sufficient for gold creation.

## Gold annotation rules

For each positive paper, expected observations must record only values explicitly supported by the paper. Every gold assertion should retain:

- reported property;
- printed value and unit;
- material association;
- experiment type;
- environment/test-condition association where necessary;
- reported reference electrode for potential quantities;
- source page and exact supporting evidence;
- ownership as focal work.

Do not pre-convert units, reference-electrode scales, corrosion rates, or normalization bases in the gold file. Gold should reflect the source, not a derived interpretation.

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
- Rct and Rp are not silently interchanged;
- corrosion/pitting/repassivation/breakdown potentials without a reported reference electrode are quarantined;
- unresolved condition conflicts remain unresolved;
- the negative control is not routed to corrosion merely because it contains generic electrochemistry or EIS terminology.

## Run policy

Benchmark preparation and scorer tests are fully offline. Live Gemini extraction begins only after:

1. all eight corpus PDFs are selected and checksummed;
2. gold assertions are manually verified;
3. offline scorer tests pass;
4. the full repository regression is green.

Benchmark mode remains pinned: no credential failover and no silent model substitution during a scored run unless the benchmark contract is explicitly revised.

## Stage 3 exit gate

Stage 3 is complete only when the fixed corpus has been run, every paper has an archived result or explicit expected rejection, score reports are saved, safety controls pass, and the full regression suite remains green.
