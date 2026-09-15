# Catalysis / Electrocatalysis V1 — Stage 3 Final Closure Report

Date: 2026-09-15

Outcome: **CLOSED — Stage 3 confirmation complete. Ready to begin Stage 4 freeze.**

This report records the cumulative final confirmation of Catalysis / Electrocatalysis V1 Stage 3. Historical Stage 3 benchmark artifacts and prior remediation reports remain intact and are not overwritten by this closure record.

## Final closure basis

1. Repository regression suite after the final scoring changes: **240 passed, 2 warnings**.
2. The fixed seven-paper Stage 3 corpus is cumulatively resolved without requiring another full seven-paper Gemini rerun.
3. Routing, scope classification, subtype classification, strict schema validation, evidence handling, ownership protection, admission/quarantine rules, DFT separation, and the existing safety gates remain unchanged.
4. Provider failures encountered during the first final confirmation were explicitly distinguished from scientific failures. Later resume runs retried only unresolved papers and preserved prior successful results.
5. `CAT-GOLD-A` reached **8/8** metric association under conservative scoring normalization.
6. `CAT-GOLD-B` reached **4/4** metric association plus **2/2** normalization-source review.
7. Gold B normalization remains scientifically conservative: the paper's `mA cm-2` values do not, by themselves, establish geometric-area normalization. The correct reviewed expectation is unknown/absent unless explicitly stated by the source.
8. Gold B's final 4/4 result required no weakening of extraction or scientific admission rules. The saved schema-valid extraction already contained all four target measurements; the remaining discrepancy was benchmark interpretation of typed feed arrays, nested potential objects, and the potential reference scale.
9. Final scoring normalization now recognizes those typed representations without changing the underlying scientific records.
10. `CAT-COMPUTE-C` passed.
11. `CAT-STABILITY-D` passed.
12. `CAT-REVIEW-E` passed.
13. `CAT-PHOTO-F` passed within its deferred/out-of-scope policy boundary.
14. `CAT-NEGATIVE-G` passed as the routing-only negative control.
15. Final safety gates remained clean: no DFT-to-experiment leakage, no review contamination into canonical scientific records, no digitized-value canonical leakage, no unsupported potential conversion, and no referential-integrity failure was introduced by the closure work.
16. No Serper calls were used in benchmark confirmation.
17. No further Gemini rerun is required for Stage 3 closure.

## Final Stage 3 paper status

| Benchmark ID | Final status | Closure note |
| --- | --- | --- |
| CAT-GOLD-A | PASS | 8/8 Gold metric association |
| CAT-GOLD-B | PASS | 4/4 metric association; 2/2 normalization-source review |
| CAT-COMPUTE-C | PASS | Schema-valid computational paper path |
| CAT-STABILITY-D | PASS | Schema-valid stability/deactivation path |
| CAT-REVIEW-E | PASS | Review contamination safeguards preserved |
| CAT-PHOTO-F | PASS | Correctly handled under deferred photocatalysis boundary |
| CAT-NEGATIVE-G | PASS | Correct routing-only negative control |

## Scoring corrections made during closure

The final confirmation exposed two benchmark-interpretation issues that were corrected without modifying source evidence, Gold scientific facts, or canonical admission policy:

- Gold A scoring normalization: display-equivalent productivity units and explicit CO2 methanation chemistry are conservatively matched to the curated Gold associations.
- Gold B typed-context normalization: structured feed composition, nested potential objects, and `reported_reference` are projected into comparison values only for benchmark interpretation.

These corrections are intentionally narrow. They do not perform arbitrary dimensional conversion, infer unsupported normalization bases, infer missing chemistry, or relax association requirements.

## Stage 4 decision

**Ready to begin Stage 4 / freeze Catalysis V1: YES.**

Stage 4 should now focus on hardening and freeze activities only: documentation alignment, final version/status cleanup, frozen acceptance criteria, and regression-preserving packaging. It should not reopen Stage 3 scientific extraction behavior unless a new independently justified defect is found.
