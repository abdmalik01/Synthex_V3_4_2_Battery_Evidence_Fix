# Catalysis V1 Stage 3 - Gold A Follow-up Report

Date: 2026-09-14

Outcome: **FAILED CHECKPOINT - NOT READY FOR STAGE 4**

This follow-up was limited to diagnosing and recovering two explicit native-prose Gold A conversion measurements. It did not begin Stage 4, rerun the seven-paper corpus, change Catalysis scientific models or admission rules, or overwrite any Stage 3/remediation report, summary, or ledger.

## Pre-edit two-target trace

| Target | Raw Gemini JSON | Repaired JSON | Strictly validated | Postprocessed | Quarantined | Assembled | Matcher candidate |
|---|---|---|---|---|---|---|---|
| MMONiCo, approximately 80% CO2 conversion at 350 °C | Historical successful response was not retained; the retained validated document omitted it | None; no repair occurred | Absent | Absent | No target entry | Absent | None |
| MMONiFe, 50% CO2 conversion at 350 °C | Historical successful response was not retained; the retained validated document omitted it | None; no repair occurred | Absent | Absent | No target entry | Absent | None |

The earlier 115-error malformed response itself is not stored in the repository. The offline recovery fixture preserves its schema-drift pattern, but not the original full response or these two exact observations. The contemporaneous Stage 3 brief records that the malformed response had identified CO2 conversion values, catalyst names, and 350 °C. This historical statement is consistent with the source but cannot substitute for the missing raw artifact.

## Required result record

1. **Exact missing target 1:** MMONiCo; CO2 methanation/hydrogenation; CO2 conversion; raw value `~80 %`; qualifier `approx`; temperature `350 °C`.
2. **Exact missing target 2:** MMONiFe; CO2 methanation/hydrogenation; CO2 conversion; raw value `50 %`; qualifier `exact` only if represented as printed; temperature `350 °C`.
3. **Source evidence for target 1:** page 9, section 3.2.2 states that the Co-containing material experienced better CO2 conversions, approximately 80% at 350 °C.
4. **Source evidence for target 2:** the same contiguous native-prose sentence contrasts the Fe-containing material at 50% and 350 °C.
5. **Latest raw Gemini response:** both target metrics are absent. The captured response is `outputs/gold_a_followup/cat-gold-a_raw_gemini_response.json`, 23,592 characters, SHA-256 `011596F0D0AFE3CD1255B0BD30DC0DBFFC2B35AEE0045A21AAFBBF93528BF961`.
6. **Repair response:** none. The latest response passed strict validation on its first attempt; Gemini calls = 1 and repair calls = 0.
7. **Validated CatalysisDocument:** both target metrics are absent. The document contains six STY/productivity metrics and two stability conversion observations, but not the focal page-9 comparison.
8. **Postprocessed CatalysisDocument:** both remain absent. Postprocessing did not remove them because it never received them.
9. **Evidence/admissibility audit:** neither target was quarantined; no target object existed to evaluate. The complete run admitted zero quantitative values and quarantined 18 objects/values for existing evidence/admission reasons.
10. **Assembled SynthexArchive:** neither target is present. The archive contains no admitted Gold A experiment output in this run because the model emitted catalyst records without verified catalyst evidence, causing experiment linkage/admission failure.
11. **Benchmark observations:** neither target produced a candidate, so this is not a matcher miss. Correct-number/wrong-catalyst, wrong-temperature, or wrong-property cases continue to fail offline matching tests.
12. **Exact failure layer:** primary model extraction/output selection before the strict validation boundary. The existing V1 schema already represents both observations; neither model, postprocessor, assembler, nor matcher changes are required for representability.
13. **Why the malformed response found them while schema-correct runs omitted them:** the earlier loose/stale contract allowed scientifically broad but structurally invalid output. The current prompt is approximately 103,725 characters, including a 22,680-character schema contract and full source/context. The latest raw output was complete valid JSON rather than a token-truncated fragment. Evidence points to one-pass model selection under a broad extraction task, not schema inability, repair pruning, postprocessing, deduplication, or output-token exhaustion. Exact causation cannot be proven because the original malformed raw response and provider finish metadata were not retained.
14. **Prompt/object-priority finding:** the 2/8 remediation response contained only two catalysts, one preparation, zero characterizations, and two experiments, so characterization did not consume its output budget. It stopped after two members of a six-member STY list. The follow-up priority instruction restored the complete STY list, showing that representative-object selection/completeness was the relevant behavior.
15. **Four additional 6/8 to 2/8 regressions:** MMONi + Ce = 148, MMONiFe + Ce = 108, MMONi = 105, and MMONiFe = 80 mol CH4 h-1 L-1, all at 350 °C for CH4 productivity in hydrogenation.
16. **Regression classification:** all four were genuine model-output selection omissions in the 2/8 response, not new quarantine, matcher change, or a more conservative score. The follow-up raw response restored all four and the benchmark returned to 6/8. The 105 record retains a source-text caveat: the native prose/parser reads `OMNi`; it matched the curated MMONi identity at the validated benchmark layer but was not canonically admitted.
17. **Files modified:** `synthex_platform/extraction/catalysis_extractor.py` (prompt prioritization plus ephemeral response capture), `synthex_platform/extraction/pipeline.py` and `benchmark_catalysis_stage3.py` (opt-in controlled-run capture only), `tests_v3/test_catalysis_stage3_remediation.py`, new `benchmark_catalysis_gold_a_followup.py`, new follow-up outputs/ledger/summary, and this report. No Catalysis model, postprocessor, assembler, matcher, Gold record, or Gold B code was changed in this follow-up.
18. **Exact minimal scientific fix:** one prompt paragraph now prioritizes focal heterogeneous catalyst identity, reaction conditions, fully associated focal performance, and stability before exhaustive optional detail; forbids representative subsets; and requires comparative prose/list expansion into one metric per catalyst-condition pair while preserving qualifiers. It contains no Gold A names or numbers.
19. **Offline tests added:** a mocked generic comparison (`Catalyst A ~80%` versus `Catalyst B 50%`, both at 350 °C) verifies two separate conversion metrics, correct catalyst and temperature association, metric type, `~80 %` plus `approx`, native evidence, no duplication, archive survival, and rejection of wrong catalyst/temperature/property matches.
20. **Focused test result:** 32 passed, one existing google-genai deprecation warning. This included the Gold A remediation tests, structured-output recovery tests, and benchmark association tests. The narrower updated file alone passed 8 tests.
21. **Gold A checkpoint result:** routing, scope, and subtype checks passed; the first Gemini response was schema-valid; no repair occurred; stability association remained 1/1; representative metric association was 6/8; both required conversions failed. No retry was made.
22. **Approximation handling:** the offline path preserves target 1 as raw `~80 %` with qualifier `approx`. The live response emitted no target, so no live approximation was altered or admitted. Target 2 is modeled as raw `50 %` with `exact` in the fixture because the source prints no approximation marker.
23. **Evidence verification:** the PDF page and native parser both contain the exact contiguous comparison. No OCR, figure digitization, or search evidence was used. Live Evidence objects for the two targets do not exist because the model omitted both.
24. **Gold B and canonical safety:** the follow-up wrote only Gold A-specific paths. Existing Gold B 4/4 product, potential/reference, and feed associations and its 2/2 unknown normalization review were not overwritten. The new Gold A run reported zero false admissions, zero review contamination, zero DFT leakage, zero digitized canonical leakage, zero unsupported potential conversions, and zero referential-integrity failures. Because there were zero canonical admissions, the per-run precision helper reports `0.0` by empty-denominator convention; this is not a false-admission regression and does not replace the historical Stage 3 precision of 1.0.
25. **External calls and gated validation:** one completed Gemini extraction call, zero repair calls, zero Serper calls, and zero web/search calls. The complete Catalysis, shared, and repository suites were not rerun after the failed live checkpoint because the instruction says to stop if either conversion remains missing. The last completed results remain 55 Catalysis tests and 180 repository tests with two existing warnings from the preceding remediation.
26. **Remaining limitation and decision:** a further bounded remediation is scientifically justified only if it changes the extraction method rather than repeating prompt-only runs for a favorable sample - for example, a deterministic native-prose performance-candidate inventory followed by Gemini interpretation, with the same strict evidence/admission safeguards. Another wording-only retry is not justified. **READY FOR STAGE 4: NO.**

## Preservation

The protected historical files were not overwritten. The seven-paper corpus was not rerun. Batteries V1, Visual Intelligence V1, Gold B scientific behavior, the Catalysis V1 schema, and canonical admission policy remain unchanged.
