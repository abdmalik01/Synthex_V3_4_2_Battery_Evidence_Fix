# Catalysis V1 Stage 3 Candidate-Recovery Report

Status: **bounded implementation complete; live Gold A gate not passed because Gemini returned 503 before producing primary JSON**.

This report is additive. It does not replace or revise `STAGE3_REPORT.md`,
`STAGE3_REMEDIATION_REPORT.md`, `STAGE3_GOLD_A_FOLLOWUP_REPORT.md`, or their
historical summaries and ledgers.

## 1. Captured Gold A Gemini JSON review

The saved follow-up response contains six of the eight representative metrics:

1. MMONiCo + Ce productivity: 168 mol CH4 h-1 L-1 at 350 °C.
2. MMONiCo productivity: 150 mol CH4 h-1 L-1 at 350 °C.
3. MMONi + Ce productivity: 148 mol CH4 h-1 L-1 at 350 °C.
4. MMONiFe + Ce productivity: 108 mol CH4 h-1 L-1 at 350 °C.
5. MMONi productivity: 105 mol CH4 h-1 L-1 at 350 °C.
6. MMONiFe productivity: 80 mol CH4 h-1 L-1 at 350 °C.

It does not contain the MMONiCo approximately 80% conversion or the MMONiFe
50% conversion at 350 °C. The JSON is structurally complete, validates on the
first response, includes all six ordered productivity values and multiple
catalyst/preparation/stability records, and ends normally. The pattern is
selective scientific-output omission. It is not token truncation, repair loss,
list compression, deduplication, or wholesale catalyst-variant pruning.

## 2. Candidate-inventory architecture

`SourceBundle` is the sole source authority. A deterministic pass identifies
bounded quantitative passages, a deterministic coverage pass compares them
with the already validated primary `CatalysisDocument`, and only uncovered
high-priority candidates are eligible for one batch semantic call. A strict
additions-only response is provenance-checked and merged into a copy of the
validated document. The merged document then follows the existing evidence
verification, postprocessing, admission/quarantine, and assembly path.

## 3. Candidate model fields

`CatalysisQuantitativeCandidate` contains deterministic ID, source ID and
checksum, page, optional section, exact snippet, numeric spans, unit spans,
manifest-derived lexical cues, origin, optional table/figure/cell locator,
ranking score, and priority.

## 4. Candidate discovery rules

Discovery requires both a numeric span and a Catalysis performance, kinetics,
or stability cue from the existing manifest. It retains comparative clauses as
one block and includes a bounded preceding sentence when pronouns such as
"material containing", "former/latter", or "respectively" require that context.
Figure/table labels and citation numbers are excluded from numeric spans.
Native page text wins; accepted OCR is used only on an OCR-selected page.
Verified table cells and figure captions remain distinct origins. Digitized
curves, Serper snippets, and web text are excluded.

## 5. Ranking rules

Ranking is lexical and deterministic: cue count, raw units, multiple numbers,
and comparative wording increase priority; prior-work/literature/example cues
reduce it. High priority requires an explicit unit. Ranking never establishes
metric type, ownership, catalyst association, focality, or admissibility.

## 6. Why the inventory is not scientific extraction

The inventory emits source passages and surface spans only. It cannot create a
`HeterogeneousMetric`, choose a reactant/product, assign a value to a catalyst,
declare focal work, or admit a canonical record. Gemini remains the semantic
interpretation boundary and the normal deterministic admission policy remains
the only canonical gate.

## 7. Coverage-matching algorithm

Coverage requires the same source/page/origin and strong evidence-snippet
overlap. Numeric spans must be represented by metrics plus their linked parent
conditions. A repeated number on a different page or in another snippet is not
coverage. Every value in a comparative candidate must be represented; one of
two conversions is partial coverage, not covered.

## 8. Coverage-recovery prompt and contract

The one-call prompt receives only a compact validated-document summary,
uncovered candidates and locators, and a concise schema generated from strict
Pydantic recovery models. Every candidate must receive an accepted/rejected
disposition. Accepted output is additions only. The prompt forbids invented
fields, derivation, inferred normalization, potential conversion, area
normalization, and reinterpretation of plotted estimates. There is no recovery
response repair attempt.

## 9. Safe merge rules

Candidate IDs must be requested and unique; evidence must use the authoritative
source ID/page/origin/locator and be an exact normalized substring of the
candidate. References must resolve. Existing catalyst identity cannot change;
new catalysts are limited to a supported reported name, ownership and exact
evidence. Duplicate scientific signatures are skipped. Competing values are
stored as unresolved `CatalysisConditionConflict` records and never overwrite
existing values. All candidate numeric spans must be covered after the proposed
merge, then the full `CatalysisDocument` validates again. Recovery has no
privileged admission route.

## 10. Files created or modified

Created:

- `synthex_platform/extraction/catalysis_candidate_inventory.py`
- `tests_v3/test_catalysis_candidate_inventory.py`
- `benchmark_catalysis_candidate_recovery.py`
- this report
- new candidate-recovery summaries, ledger, checkpoint result, sidecar and
  offline replay diagnostic under `benchmark/catalysis_v1/outputs/`

Modified:

- `synthex_platform/extraction/pipeline.py`
- `synthex_platform/extraction/catalysis_evidence.py`
- `synthex_platform/extraction/catalysis_postprocess.py`
- `synthex_platform/extraction/catalysis_assembler.py`
- `benchmark_catalysis_stage3.py` (new optional capture flag only)

No Batteries or Visual Intelligence model was changed.

## 11. Offline tests added

Tests cover one-value and comparative sentences, approximation, temperature,
multiple catalysts, repeated numbers on different pages, non-catalytic and
background prose, native/OCR precedence, deterministic IDs, exact contextual
coverage, malformed responses, unsupported evidence, duplicate suppression,
conflict preservation, one-call pipeline behavior, normal admission, Catalysis
NUL parser separators, and stability parent-reference linkage.

## 12. Focused test results

- Candidate/recovery focused: **17 passed**.
- All Catalysis tests after the implementation: **74 passed, 68 deselected**.
- Existing third-party warning: one `google.genai` deprecation warning.

## 13. Gold A candidates detected

The offline replay against the authoritative PDF and the previously captured
validated primary response detected 24 candidates: 16 high priority and 8
medium/low priority.

## 14. Gold A candidates deemed uncovered

Two candidates were deterministically covered; 14 high-priority candidates were
uncovered. The target page 9 passage is high-priority candidate
`catcand-d993e51db7fe1ace`, with numeric spans `~80`, `350`, `50`, `350`, and
origin `native_text`. False-positive surface candidates remain safe because
Gemini must reject them and merge/admission remain strict.

The live run itself recorded zero inventory rows because the primary provider
call failed before a validated document existed. The 24/16/14 counts are
explicitly an offline replay of the previously captured valid primary JSON.

## 15. Primary Gemini calls

One authorized primary request reached Gemini and returned `503 UNAVAILABLE`
without JSON. A preceding sandboxed attempt was blocked locally by Windows
socket policy (`WinError 10013`) and did not reach the provider. Both attempts
are retained in the new execution ledger.

## 16. Schema repair calls

Zero. No primary JSON was returned, so no schema validation or repair was
possible.

## 17. Coverage calls

Zero. The coverage call is downstream of a validated primary response and was
correctly not invoked.

## 18. Recovery dispositions

None from the live checkpoint. No coverage response exists to accept or reject.

## 19. MMONiCo conversion result

The deterministic inventory found the native `~80 % at 350 °C` passage and
preserved the approximate token. Live semantic recovery: **not evaluated due
to upstream Gemini 503**.

## 20. MMONiFe conversion result

The same candidate preserved the native `50 % at 350 °C` comparison and both
catalyst names. Live semantic recovery: **not evaluated due to upstream Gemini
503**.

## 21. Final Gold A score

No new scientific score was produced. The checkpoint status is
`pipeline_error`, the gate is false, and the last trusted historical Gold A
score remains 6/8 representative metrics with 1/1 stability association.

## 22. Gold A canonical-admission analysis

For the six captured representative productivity metrics, zero are presently
scientifically eligible for canonical admission because the source/model record
does not establish an admissible normalization basis. The benchmark stability
conversion is explicit focal native prose and is eligible. After the bounded
linkage fix it admits. A second redundant stability statement from another
source location also admits as a separate raw stability object; deduplicating
corroborating stability statements is a remaining limitation, not a reason to
weaken admission.

The offline captured-response reanalysis reports four admitted quantitative
values in the aggregate audit, including process parameters; two canonical
experiment outputs are stability conversions. None of the six productivity
metrics admits.

## 23. Exact quarantine reasons for focal Gold A metrics

- MMONiCo + Ce productivity 168: `normalization_basis_unknown`.
- MMONiCo productivity 150: `normalization_basis_unknown`.
- MMONi + Ce productivity 148: `normalization_basis_unknown`.
- MMONiFe + Ce productivity 108: `normalization_basis_unknown`.
- MMONiFe productivity 80: `normalization_basis_unknown`.
- MMONi productivity 105: its parent material first fails
  `no_value_specific_evidence` because the linked native snippet prints `OMNi`;
  the experiment therefore fails `schema_invalid`. Even with that reference
  repaired, the productivity metric would remain ineligible because its
  normalization basis is unknown.
- The benchmark `~85% after 1400 min` stability conversion previously failed
  through an assembler/reference dependency. Exact child evidence is now linked
  only to the explicitly named existing catalyst, and stability can resolve the
  material through its valid parent experiment reference. It now admits through
  normal evidence and admission checks.

No ownership, derived-value, condition-conflict, unsupported-origin, OCR, or
digitization failure explains the six productivity quarantines.

## 24. Gold B regression result

Not run. The instructions permit Gold B only after the Gold A gate passes. The
last trusted result remains values/units 4/4, products 4/4,
potentials/references 4/4, feeds 4/4, and normalization correctly unknown 2/2.

## 25. Canonical precision

No new live value is available. The historical trusted value remains **1.0**;
offline tests show that recovery additions still pass normal admission.

## 26. False admissions

No new live value is available. Offline recovery tests produced **0 known false
admissions** and deliberately reject unsupported evidence.

## 27. Review contamination

Not remeasured because the Gold A gate failed. Last trusted value: **0**.

## 28. DFT leakage

Not remeasured because the Gold A gate failed. Last trusted value: **0**.

## 29. Unsupported potential conversions

Not remeasured because the Gold A gate failed. Last trusted value: **0**.

## 30. Digitized leakage

Not remeasured because the Gold A gate failed. Last trusted value: **0**.

## 31. Referential-integrity failures

Offline focused tests: **0**. Full-corpus value was not remeasured after the
failed gate; last trusted value remains **0**.

## 32. Catalysis test result

**74 passed, 68 deselected, 1 existing warning** after all implementation and
linkage changes.

## 33. Complete repository result

Not run. Phase 16 explicitly conditions the complete suite on a passing Gold A
live gate. The last trusted historical full-suite baseline remains **180 passed,
2 existing warnings**; it is not claimed as validation of this change set.

## 34. External calls

- Gemini: one primary request reached the provider and returned 503; no model
  content was returned.
- Local blocked socket attempt: one, before provider access.
- Gemini coverage: zero.
- Gemini schema repair: zero.
- Serper/search/web: zero.

## 35. Seven-paper rerun result

Not performed. The Gold A gate did not pass, so the explicit stop condition was
honored.

## 36. Remaining limitations

- A provider-available Gold A checkpoint is still required.
- Lexical inventory intentionally over-collects some equations, preparation
  conditions, and broad performance prose; strict semantic rejection is the
  safety boundary.
- Candidate discovery is bounded sentence/prose heuristics, not discourse
  parsing.
- Corroborating stability statements can remain as separate validated raw
  stability objects.
- No graph reading, inferred values, or normalization inference is added.

## 37. Does candidate recovery materially improve robust recall?

Architecturally and offline: **yes**. The previously omitted comparison is now
deterministically surfaced as one contextual native candidate, cannot be hidden
by the same-number-elsewhere error, and can be mapped only through a typed,
single-call semantic boundary. Live recall improvement remains unconfirmed
because the provider returned no primary document.

## 38. Is another Stage 3 remediation justified?

No additional code/prompt remediation is justified from this checkpoint. The
next justified action is a provider-available rerun of the existing Gold A
checkpoint, not another architecture or wording change. If that scientific gate
fails with an actual primary and coverage response, inspect those new captured
artifacts before deciding on further work.

## 39. Stage 4 readiness

**NOT READY for Stage 4.** The bounded implementation and offline tests are
sound, but the required live Gold A conversion gate has not been demonstrated.

## Historical integrity

The following SHA-256 values match their pre-pass values:

- `STAGE3_REPORT.md`: `AF30CBEE5384E8B5FD39FD0F57CFECBA453614A619E7DA5F7DD7F323E7562845`
- `STAGE3_REMEDIATION_REPORT.md`: `D07E657DCBA08F14D728532AEBE0F7D6064ADA5616BB31D4840EFC019D564F69`
- `stage3_run_summary.json`: `5FBD3CCBB4D40507C2C3ED7FBB8B7C5348BC4EDED999BB997C37801C1E3621F2`
- `stage3_remediation_run_summary.json`: `B88C20A0CAEE8FC555486727D069EAB9D157024EF65DA5045F82B3411DD3716D`
- `execution_ledger.json`: `20546B5493DAA861300625C135AD25A9DC45479C406EAE863EBA0068BE0B0E15`
- `stage3_remediation_execution_ledger.json`: `9CF4912C436B150289BDD5FE67311A2279E765DF83FCA3EB9CB8E559FDB16B89`

