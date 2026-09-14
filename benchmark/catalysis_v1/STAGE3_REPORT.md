# Catalysis / Electrocatalysis V1 — Stage 3 report

Stage 3 is complete as a benchmark and hardening pass. The fixed corpus routes correctly, every attempted final Catalysis extraction is schema-valid, and all explicit safety targets pass. The benchmark also exposes meaningful extraction-recall and association gaps, so this report does not claim perfect scientific coverage.

## 1–5. Previous-agent audit and repository changes

1. Audited the previous agent's `benchmark/catalysis_v1/` tree, `benchmark_catalysis_corpus.py`, `benchmark_catalysis_gold.py`, and `tests_v3/test_catalysis_benchmarks.py`, along with the relevant extractor, router, pipeline, assembler, and UI paths.
2. Found that the original “gold” JSON was fictional scaffold data, manifest validation could accept weak/empty records and used incorrect field expectations, contextual matching could let context overwrite scientifically conflicting values, safety helpers were too shallow, and no normal-pipeline real-paper runner or Catalysis recovery path existed.
3. Kept the useful directory structure. Replaced the benchmark helpers and tests, moved the fictional records to explicitly non-scorable `fixtures/templates/`, created real source-grounded gold, and added saved per-paper results plus a consolidated summary.
4. The old Pt/Al2O3 and Ag-particle scaffold records are not gold and never participate in scoring. Their templates carry `synthetic=true` and `scorable=false`.
5. Runtime files modified: `platform_app.py`, `synthex_platform/extraction/__init__.py`, `catalysis_extractor.py`, `pipeline.py`, and `router.py`. Benchmark/test files created or replaced: `benchmark_catalysis_corpus.py`, `benchmark_catalysis_gold.py`, `benchmark_catalysis_stage3.py`, the complete `benchmark/catalysis_v1/` assets, `test_catalysis_benchmarks.py`, and `test_catalysis_structured_output_recovery.py`.

## 6–9. Real corpus and gold

6. The exact seven required PDFs were found locally under `corpus_pdfs/`; no substitute or downloaded source was used.
7. Final mapping: Gold A = heterogeneous CO2 methanation; Gold B = CO2RR electrocatalysis; C = computational DFT; D = stability/deactivation; E = review contamination; F = deferred photocatalysis; G = gas-sensing negative control. Filenames, titles, DOI/year, roles, expected routes/scopes/subtypes, and SHA-256 checksums are fixed in `corpus_manifest.json`.
8. Gold A was independently curated from PDF pages 1–3 and 8–10. It captures the eight named catalyst variants plus an activated state, preparation routes, characterization methods, fixed-bed CO2 methanation, 40 mg catalyst, 50 mL/min flow, 36,000 h-1 GHSV, 250–400 °C testing, catalyst-specific conversion/STY values, and the 350 °C/1400 min stability association. The prose/figure stability conflict is explicitly preserved.
9. Gold B was independently curated from PDF pages 1–8. It captures polycrystalline Cu and its under-reaction hydroxyl state, electrode preparation, H-cell configuration, CO2/O2 feeds, electrolyte/pH/reference electrode/iR handling, product- and potential-specific metrics, and focal DFT settings/output separation.

## 10–14. Gold A root cause and recovery

10. The 115-error failure was output-contract drift: Gemini followed a stale/imagined shape (`name`, `chemical_formula`, `process`, string reactions, `performance_metrics`, and pipeline metadata inside `source`) rather than the strict current `CatalysisDocument` hierarchy.
11. The extractor prompt now embeds a concise contract derived from `CatalysisDocument.model_json_schema()`, with explicit required IDs, enum literals, exact nested structures, evidence objects, reactions, preparations, characterizations, experiment families, stability, and calculations. A full provider-side response schema was tested once and removed after Gemini rejected it as `INVALID_ARGUMENT`; the schema-derived prompt contract remains.
12. Catalysis now performs deterministic structural normalization, strict validation, at most one constrained repair using exact Pydantic errors plus bounded source context and the actual contract, then strict validation again. Persistent failure raises `CatalysisStructuredExtractionValidationError` and admits nothing.
13. Deterministic normalization is limited to singleton wrappers on known list fields, verified stripping of the three SourceBundle-owned keys, the exact `in_scope`→`supported` alias, exact evidence-string promotion only after a unique local page match, and the observed unambiguous enum typo `catalyst_character_characterization`→`catalyst_characterization`. No fuzzy scientific field mapping or generic extra-field deletion exists.
14. Streamlit catches the typed generic/Catalysis validation errors and shows a concise failure, route/source/error count, repair status, and raw-output hash reference without dumping a giant response or traceback. Diagnostics survive provider failures.

## 15–22. Real extraction and field-level results

15. Gold A final: schema-valid on its first retained call; 6/9 catalyst identity/state records, 0/5 component sets, 0/8 asserted states, 1/2 preparation records, 6 heterogeneous experiments, 1/1 stability association, and 0/1 explicit conflict record. It matched 6/8 representative full metrics; the six STY associations matched and the two representative conversion points were missed.
16. Gold B final: schema-valid on its first call; 1/2 catalyst identities, 0/1 component set, 1/2 states, 2 observed preparations versus one grouped gold preparation, 3 electrocatalysis experiments, and 1/1 focal DFT calculation. Property/value/unit = 4/4, product = 4/4, and raw potential/reference = 4/4; full metric association = 0/4 because feed context was not represented and metric-level normalization basis = 0/2.
17. Other roles: DFT produced one calculation candidate and no experimental leakage, but its values remained quarantined without sufficient focal/value-specific evidence; stability produced five catalysts, four heterogeneous experiments, and three stability records after one repair, with no quantitative admission; review preserved five review-summary catalysts and five review-summary experiments with zero canonical admission; photocatalysis remained deferred and quarantined all 14 candidates; gas sensing routed to `gas_sensing` and consumed no Gemini call.
18. Routing accuracy = 7/7 (100%).
19. Final-result first-response schema validity = 5/6 (83.3%) among Catalysis papers.
20. Repair schema validity = 1/1 (100%); final attempted-extraction schema validity = 6/6 (100%); persistent final failures = 0.
21. Gold A: catalyst identity 6/9, components 0/5, states 0/8, property/value/unit 6/8, condition association 6/8, product association 6/8, stability 1/1, and native-text evidence objects 21.
22. Gold B: catalyst identity 1/2, components 0/1, states 1/2, property/value/unit 4/4, condition association 0/4, product 4/4, potential/reference 4/4, normalization 0/2, DFT separation 1/1, and native-text evidence objects 26.

## 23–30. Scientific safety and benchmark-driven fixes

23. Final corpus admission audit: 9 policy-valid quantitative admissions, 0 observed false admissions, 71 correct quarantines, 0 incorrect quarantines; policy-gate canonical precision = 1.0. This is a precision/safety audit, not an assertion that the representative gold is exhaustive.
24. Review contamination = 0. Strong review-table content did not override `review_summary` ownership, and cited experiments were not attributed to the review authors as focal canonical work.
25. DFT experimental leakage = 0. Computational candidates remained in `calculations`/quarantine and never became `ExperimentRecord` outputs.
26. Unsupported potential conversions = 0. Gold B preserved author-reported raw potential/reference structure without silent reference conversion.
27. Demonstrated association failures: Gold B omitted feed context from the current experiment shape and failed to repeat the stated geometric-area basis at metric level; Gold A missed two conversion targets. Products and Gold B potential/reference associations were preserved correctly.
28. Gold A stability association passed 1/1. The dedicated stability paper produced three typed stability candidates but no canonical quantitative values because the strict evidence/admission gate quarantined them.
29. Referential-integrity failures = 0 across all final outputs.
30. Benchmark-driven fixes: schema-derived output contract; one-shot Catalysis repair; strict verified transport-key handling; nested evidence normalization; typed UI failure; exact enum-typo compatibility; call diagnostics on exceptional exits; false materials-informatics/deferred routing fixes; association-aware scorer; exact seven-file manifest/checksum enforcement; monotonic route/model scope enforcement preventing deferred photocatalysis from canonical admission.

## 31–36. Tests and external calls

31. Focused Catalysis benchmark/recovery result: 23 passed, 1 existing Google SDK deprecation warning. A subsequent added scope test is included in the shared/full results.
32. Shared Catalysis, generic routing/recovery, Gas Sensing routing, Batteries, Visual Intelligence, and Paper Discovery regression result: 165 passed, 1 existing warning.
33. Complete repository result: 173 passed, 2 existing warnings in 292.00 seconds. This replaces the previously trusted 149-pass baseline.
34. The final saved result set represents 7 Gemini calls: five schema-valid first calls, one stability initial call plus one repair, and zero calls for the gas-sensing control. The transparent development/verification ledger records 14 total Gemini request attempts, including superseded runs, one provider configuration rejection, and two transport failures.
35. Final saved result-set repair calls = 1; historical repair calls = 2. Every individual run remained capped at one repair per failed paper.
36. Serper calls = 0; web/search calls = 0. External activity was limited to the explicitly permitted Gemini benchmark requests. All tests were offline.

## 37–39. Remaining issues and readiness

37. Remaining demonstrated issues are extraction recall/association rather than safety failures: missing Gold A variants/states/components and conflict record, missed Gold A conversion points, missing Gold B under-reaction state/components, absent feed association, and absent metric-level normalization basis. The current `ElectrocatalysisExperiment` schema has no explicit gas-feed/flow/duration fields, so the Gold B feed gap is partly structural and should be resolved deliberately rather than hidden by scorer relaxation.
38. The stated Stage 3 acceptance targets are satisfied: 100% routing, 100% final schema validity, and zero review contamination, DFT experimental leakage, unsupported potential conversion, digitized canonical leakage, or referential-integrity failure. Scientific precision was preserved over recall.
39. Catalysis is **NOT READY for a Stage 4 freeze** because the real Gold B feed/normalization association gap and the Gold A catalyst-state/component recall gap are now demonstrated. Stage 3 itself is complete as an honest benchmark/hardening pass; Stage 4 was not started.
