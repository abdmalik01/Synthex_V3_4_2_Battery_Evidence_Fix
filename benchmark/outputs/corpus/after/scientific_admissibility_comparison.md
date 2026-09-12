# Batteries V1 scientific-admissibility comparison

## Run controls

- Frozen set: the same eight documents used by the initial corpus run.
- Serper: disabled (`SERPER_QUERY_BUDGET=0`; `SERPER_API_KEY` removed in the runner process).
- Gemini extraction: `temperature=0`, seed `0`, configured model `gemini-3.5-flash` in this environment.
- PDF ingestion: PyPDF primary, PyMuPDF non-OCR fallback.
- Local validation after implementation: **60 passed, 2 warnings**.
- Live limitation: seven documents reached a terminal local outcome, but Gemini rejected the Ziebert request with `429 RESOURCE_EXHAUSTED` for the free-tier daily request quota. This is an external-service failure, not a schema or archive failure.

## Before/after metrics

| Metric | Before | After | Interpretation |
|---|---:|---:|---|
| Routing accuracy | 8/8 | 8/8 | Negative control remains correctly rejected. |
| PDF ingestion success | 7/8 | 8/8 | The S266 font-structure failure now succeeds with PyMuPDF. |
| Strict schema success | 5/6 attempted | 6/6 attempted | Bounded `paragraph` to `text` mapping fixes the NASA interface failure without allowing arbitrary source types. |
| Canonical archive success | 5/7 in-domain | 6/7 in-domain | Six of six successfully extracted documents assembled; the seventh was blocked by Gemini quota. |
| Canonical quantitative values | 115 unverified | 55 admitted | Lower is expected under the provenance gate. |
| Quarantined quantitative candidates | Not represented | 140 | Raw values and evidence remain in the battery domain payload. |
| Records with any evidence | 86/164 (52.4%) | 125/164 (76.2%) | The live batches differ by one available paper, so this is directional rather than paired per-paper evidence coverage. |
| Records with verified verbatim evidence | Not recorded | 86/164 (52.4%) | Paraphrases do not receive full-provenance credit. |
| Normalized snippet matches | 82/87 (94.3%, offline baseline check) | 86/125 (68.8%, recorded by verifier) | The new run exposed more evidence snippets, including more paraphrases and PDF-tokenization mismatches. |
| Review focal contamination | 43 cited measurements archived | 0/29 current live review measurements archived | Regression tests also replay the exact old 43 points and admit 0. |
| Structured unresolved condition conflicts | 0 | 1 | Li2FeTiO4 `0.1 C` versus `1 C` is retained as unresolved and removed from affected point-level C-rates. |
| Referential-integrity failures | 0 observed, unenforced | 0, enforced | Invalid battery material/protocol references are warned and omitted; invalid core entity references fail validation. |
| Calculation entities | 0 | 0 live | The live first-principles document is a review, so all eight extracted values are cited and correctly quarantined. A corpus-fixture regression routes five deliberately focal-labelled DFT results to `Calculation`, not cycling experiments. |
| Duplicate signatures, all canonical numeric records | 19 | 18 | Remaining duplicates are repeated condition/process values across sample groups. |
| Duplicate canonical scientific outputs | 0 | 0 | No duplicated performance/calculation output facts were detected. |

## Per-document post-change outcome

| Document | Parser | Outcome | Admitted | Quarantined | Scientific note |
|---|---|---|---:|---:|---|
| `batteries-11-00142.pdf` | PyPDF | schema/archive success | 45 | 21 | Five target values recovered; disputed cycling C-rate is structured and unresolved. |
| `batteries-11-00011.pdf` | PyPDF | schema/archive success | 3 | 11 | EIS outputs remain canonical only where ownership and verbatim provenance pass. |
| `1-s2.0-S2666386426002407-main.pdf` | PyMuPDF | schema/archive success | 7 | 8 | Fallback fixed the prior ingestion failure without OCR. |
| `Evaluation_of_Li_Ion_Batteries.pdf` | PyPDF | schema/archive success | 0 | 71 | `paragraph` compatibility succeeds; extracted quantitative candidates were classified as cited prior work. |
| `Application_of_First_Principles_Computations_Based.pdf` | PyPDF | schema/archive success | 0 | 8 | Review values are cited prior work, not focal calculations or cycling experiments. |
| `coatings-16-00912.pdf` | PyPDF | schema/archive success | 0 | 21 | Review contamination is eliminated from canonical quantitative data. |
| `Ziebert...pdf` | PyPDF | Gemini quota failure | — | — | Exact external status: `429 RESOURCE_EXHAUSTED`, free-tier daily request limit 20 for `gemini-3.5-flash`. |
| `applsci-10-04112.pdf` | PyPDF | correctly rejected | — | — | Hard negative routed to mechanical; battery extractor skipped. |

## Li2FeTiO4 strict benchmark

| Metric | Before | After |
|---|---:|---:|
| Structural accuracy | 1.000 | 0.933 |
| Value accuracy | 1.000 | 1.000 |
| Condition-association accuracy | 0.000 | 0.600 |
| Provenance coverage | 0.000 | 0.600 |
| Overall score | 0.500 | 0.783 |

The three cycling values retain no asserted C-rate and reference one structured unresolved conflict. `121.3 mAh/g` and `108.2 mAh/g` pass value, sample, cycle, conflict, and verbatim-provenance checks. `89.2%` has the correct sample/cycle/conflict association but its generated snippet is not a normalized source substring, so it is quarantined. `1258.6 ohm` lacks both a verified verbatim match (the PDF introduces formula/token and degree-glyph differences) and the required EIS method. `1.096e-12 cm2/s` has verified evidence but lacks the required method. The missing `impedance_eis` paper type causes the structural decrement.

## Failure classes and remaining weaknesses

- **External service:** one document is incomplete solely because the Gemini project exhausted its daily free-tier request quota.
- **Prompt/model association:** the live Li2FeTiO4 result omitted the EIS paper type and method labels on resistance/diffusion facts.
- **PDF extraction:** normalized matching deliberately does not collapse arbitrary internal scientific-token spaces or all lookalike glyphs, so some otherwise plausible snippets remain unmatched; figure-only facts and scanned PDFs still require future non-OCR/OCR work.
- **Scientific ambiguity:** the Li2FeTiO4 C-rate contradiction is preserved rather than repaired, but it remains unresolved.
- **Table/figure limitation:** table text is usable when the parser exposes it, but row/column semantics and figure-only values are not deterministically reconstructed.
- **Canonical repetition:** repeated shared condition/process measurements remain across sample-specific experiments even though scientific outputs are not duplicated.
- **DFT detail depth:** focal DFT outputs route correctly to calculations, but method/model detail is limited to what Gemini places in the point method and group metadata.
- **Corpus scale:** the successful live evidence covers six battery documents plus one negative; the quota-blocked BMS/model paper still needs a post-quota rerun for a complete paired eight-document comparison.

## Readiness assessment

Batteries V1 is safer for continued controlled corpus validation, especially for evidence-bearing focal cathode/EIS measurements and review-paper contamination control. It is not ready for unattended broad production ingestion. Review values are now safely quarantined, but method association, PDF table/figure reconstruction, repeated canonical conditions, computational model detail, and external-service completion still require work.

## Changed implementation and documentation files

- `synthex_platform/extraction/battery_evidence.py` — new normalized-verbatim verifier.
- `synthex_platform/extraction/battery_models.py` — bounded ownership, evidence audit fields, conflicts, parser provenance, and strict source-type compatibility.
- `synthex_platform/extraction/battery_extractor.py` — ownership/conflict/DFT prompt rules, deterministic Gemini configuration, and evidence verification.
- `synthex_platform/extraction/battery_postprocess.py` — deterministic removal of disputed point-level C-rates.
- `synthex_platform/extraction/battery_assembler.py` — admissibility/quarantine gate, calculation routing, reference filtering, and semantic warnings.
- `synthex_platform/core/models.py`, `synthex_platform/core/archive.py`, and `schemas/synthex_archive.schema.json` — canonical evidence audit fields and referential-integrity validation.
- `synthex_v2/pdf_utils_v2.py` and `requirements.txt` — PyMuPDF non-OCR fallback and dependency.
- `benchmark_battery_material.py` — verified benchmark provenance and structured-conflict checks.
- `benchmark_battery_corpus.py` — before/after metrics, parser/admissibility/calculation/conflict/reference reporting, scoped resume, and repository-anchored output selection.
- `benchmark/batteries_v1/batteries_11_00142_gold_document.json` — focal ownership, unresolved C-rate conflict, and corrected literal resistance evidence.
- `README.md` and `CURRENT_STATUS.md` — operational policy and validation snapshot.

## Tests added or strengthened

- `tests/test_battery_scientific_admissibility.py` — 11 test functions / 12 cases covering verbatim and paraphrased evidence, bounded source-type aliases, admission/quarantine, both historical review contaminations, conflict clearing, DFT calculation routing with synthetic and corpus-derived data, reference integrity, and the exact S266 fallback PDF.
- `tests/test_battery_benchmark_strict.py` — gold evidence is now verified against the real PDF before provenance credit is awarded.
- `tests/test_battery_hardening.py` — deterministic Gemini configuration and gated archive expectations.
- `tests/test_battery_v33.py`, `tests/test_battery_process_evidence_v342.py`, and `tests_v3/test_battery_vertical.py` — existing assembly fixtures now state focal ownership and provide source text under the stricter policy.

Generated baseline and post-change artifacts are preserved as 28 files under `benchmark/outputs/corpus/before/` and 32 files under `benchmark/outputs/corpus/after/`, respectively. The latter includes every available raw model response, validated document, archive, per-paper report, run state, aggregate JSON report, transient/error records, and this comparison.
