# Catalysis / Electrocatalysis V1 — Stage 3 Remediation Report

Date: 2026-09-14

Outcome: **PARTIAL — Gold B repaired; Gold A completeness gate not met.**

This was a bounded post-Stage-3 remediation. It did not begin Stage 4, freeze Catalysis V1, alter Batteries V1 or Visual Intelligence V1, add dependencies, or change the fixed seven-paper corpus. The complete seven-paper remediation rerun was deliberately not started because the required Gold A/Gold B checkpoint did not fully pass.

## Required closure record

1. The pass was limited to the eight previously observed misses: two Gold A conversion metrics, four Gold B feed associations, and two Gold B normalization-basis expectations.
2. Historical Stage 3 remains the authoritative completed benchmark. No historical report, run summary, execution ledger, gold record, or per-paper result was overwritten.
3. The historical baseline remains 173 tests passed with two warnings, routing 7/7, final schema 6/6, nine canonical admissions, zero false canonical admissions, 71 correct quarantines, and canonical precision 1.0.
4. Final SHA-256 verification is unchanged: `STAGE3_REPORT.md` = `AF30CBEE5384E8B5FD39FD0F57CFECBA453614A619E7DA5F7DD7F323E7562845`; `outputs/stage3_run_summary.json` = `5FBD3CCBB4D40507C2C3ED7FBB8B7C5348BC4EDED999BB997C37801C1E3621F2`; `outputs/execution_ledger.json` = `20546B5493DAA861300625C135AD25A9DC45479C406EAE863EBA0068BE0B0E15`.
5. Both source PDFs were inspected as native PDFs before code changes, including rendered page checks of Gold A page 9 and Gold B pages 2, 3, and 8.
6. Every miss was classified before implementation. The complete machine-readable trace is in `remediation/diagnostic_table.json`.
7. Gold A miss 1, MMONiCo CO2 conversion of approximately 80% at 350 °C, is explicitly stated in native prose on page 9, section 3.2.2.
8. Gold A miss 2, MMONiFe CO2 conversion of 50% at 350 °C, is explicitly stated in the same native-prose sentence.
9. Those two values are also visually represented in Figure 9B, but their benchmark provenance is native prose; they must not be treated as figure-digitized estimates.
10. The Gold A failure was classified at model extraction: the accepted strict document omitted both metrics, and the deterministic postprocessor contains no metric-deletion behavior.
11. Historical raw Gemini text was not retained by the Stage 3 runner, so the earliest auditable retained boundary is the validated/postprocessed document saved in the archive payload.
12. Gold B explicitly reports the O2-containing n-propanol value, approximately 0.5 mA cm-2 at -0.75 V RHE, in native prose on page 2.
13. Gold B explicitly reports that a similar n-propanol partial current density under pure CO2 requires -1.00 V RHE.
14. Gold B explicitly reports methane onset at -0.75 V RHE when O2 is present.
15. Gold B explicitly reports methane onset at -0.95 V RHE without O2.
16. The historical model output separated pure-CO2 and CO2/O2 parent experiments, but `ElectrocatalysisExperiment` lacked a typed feed field; assembly and scoring therefore had no feed context to inherit. This was a schema-contract, assembly, and matcher-path gap—not evidence loss.
17. `ElectrocatalysisExperiment.feed_composition` was added using the existing strict `FeedComponent` model. No new scientific vertical or permissive extra-field handling was introduced.
18. Canonical metric outputs now retain their parent experiment's structured `feed_composition` in conditions.
19. Benchmark observation now derives only two conservative feed labels from typed parent membership: CO2 alone is `pure CO2`; CO2 plus O2 is `O2-containing CO2 feed`.
20. Association remains strict: an equal value attached to the wrong or missing feed does not match, and metrics are not allowed to infer feed from product, potential, or prose elsewhere.
21. Gold B contains no explicit `geometric`, `normaliz`, or `electrode area` statement establishing the current-density denominator. Page 8 reports electrode dimensions, while pages 2–3 report mA cm-2 values.
22. Under the scientific admission rule, mA cm-2 units and electrode dimensions do not by themselves prove geometric-area normalization. The correct extracted basis is unknown/absent and the partial-current-density values remain quarantined.
23. The two unsupported historical normalization expectations were not edited. A separate `remediation/gold_adjustments.json` overlay removes them only for remediation scoring and evaluates two explicit `unknown_or_absent` expectations.
24. The extraction and repair prompts now require every explicit native-prose metric to be preserved even when illustrated in a figure, require electrocatalysis feed at the parent experiment, require distinct experiments for distinct feed regimes, and forbid normalization inference from units or electrode dimensions.
25. Strict Pydantic validation, ownership protection, normalization admission rules, potential-reference rules, evidence verification, and digitized-value exclusion remain unchanged.
26. The initial focused offline remediation run passed: 26 tests passed, one third-party deprecation warning.
27. The complete Catalysis-focused offline run passed: 55 tests passed, one third-party deprecation warning.
28. The full repository suite passed: 180 tests passed, two warnings, in 374.74 seconds.
29. The first Gold-only command was blocked by the managed network sandbox with Windows socket error 10013. It produced no successful external response; the failed attempt is retained in the separate remediation ledger.
30. The authorized network-enabled Gold-only run completed three Gemini calls: one Gold A call and two Gold B calls, the second Gold B call being the single bounded schema-repair attempt. Serper calls: 0. Web/search calls: 0.
31. Gold B passed the remediation targets: full metric association 4/4, feed-condition association 4/4, and scientifically correct unknown/absent normalization 2/2. It used strict schema recovery, had zero DFT/review/digitized/referential-integrity safety violations, two canonical admissions, zero false canonical admissions, and four correct quarantines.
32. Gold A failed the checkpoint: the first response was schema-valid but matched only 2/8 expected metrics, versus the historical 6/8. It still omitted both target conversion statements and additionally omitted four formerly matched productivity values. It had zero safety violations, two canonical admissions, zero false admissions, and five correct quarantines. This is an unresolved real-model completeness blocker, not grounds for relaxing evidence or admission safeguards.
33. Because both Gold papers did not pass, the complete seven-paper remediation rerun was not executed. No retry was made merely to improve Gold A's score.
34. Final milestone decision: Stage 3 remains historically complete and intact; this remediation is partially successful but not closure-ready. **Ready to begin Stage 4 / freeze Catalysis V1: NO.**

## Files introduced or changed by this remediation

- `synthex_platform/extraction/catalysis_models.py`
- `synthex_platform/extraction/catalysis_extractor.py`
- `synthex_platform/extraction/catalysis_assembler.py`
- `benchmark_catalysis_stage3.py` (backward-compatible output-directory/gold-record injection plus feed-aware observation)
- `benchmark_catalysis_remediation.py`
- `tests_v3/test_catalysis_stage3_remediation.py`
- `benchmark/catalysis_v1/remediation/diagnostic_table.json`
- `benchmark/catalysis_v1/remediation/gold_adjustments.json`
- `benchmark/catalysis_v1/outputs/remediation/gold-only/` (new per-paper results and sidecars)
- `benchmark/catalysis_v1/outputs/stage3_remediation_run_summary.json`
- `benchmark/catalysis_v1/outputs/stage3_remediation_execution_ledger.json`
- `benchmark/catalysis_v1/STAGE3_REMEDIATION_REPORT.md`

## Remaining bounded blocker

The strict schema can represent and retain the two Gold A conversion facts, and offline regression coverage proves that path. The real model nevertheless chose an incomplete subset of the source's explicit metrics in its single permitted checkpoint run. Any future follow-up should target extraction completeness or deterministic candidate prompting for explicit prose metrics while preserving current evidence, ownership, normalization, and admission safeguards. It must be a separately authorized pass; it is not Stage 4.
