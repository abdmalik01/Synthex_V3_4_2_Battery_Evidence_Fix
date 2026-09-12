# Batteries V1 controlled corpus report

## Run controls

- Initial frozen batch: eight unique documents (seven battery-relevant documents and one hard negative).
- Model used for every Gemini attempt: `gemini-3.5-flash`.
- Serper was disabled by removing `SERPER_API_KEY` from the run process and setting `SERPER_QUERY_BUDGET=0`.
- The battery schema, prompt, post-processing, and archive assembler were not changed during or after individual papers.
- Successful PDF inputs were not truncated: extracted prompt lengths ranged from 26,798 to 127,618 characters, below the 180,000-character limit.
- The raw Gemini response, validated document, canonical archive, and per-paper report were saved when available.
- Baseline and post-harness test result: 49 passed, 2 warnings.

## Selected batch and outcomes

| File | Coverage role | Route | Schema/archive result | Main scientific result |
|---|---|---|---|---|
| `batteries-11-00142.pdf` | Cathode synthesis, fabrication, cell assembly, performance, EIS | batteries | Valid; archive produced | All five manual gold values recovered, but all five strict condition checks and all five provenance checks failed in this run. |
| `batteries-11-00011.pdf` | EIS/impedance and battery modelling | batteries | Valid; archive produced | Strongest extraction in the batch: EIS remained canonical and was not duplicated into general performance. |
| `1-s2.0-S2666386426002407-main.pdf` | Solid-state EIS/DRT/ML | batteries via metadata-title fallback | PDF extraction failed; Gemini not called | Existing PyPDF path cannot extract the document because its font descriptor contains both `/FontFile` and `/FontFile3`. |
| `Evaluation_of_Li_Ion_Batteries.pdf` | NASA dataset, degradation/SOH, charge/discharge and EIS | batteries | Strict validation failed; no archive | Gemini used unsupported evidence `source_type="paragraph"` ten times. Raw output was preserved and no fields were silently dropped. |
| `ZiebertEEVC2017ATable-drivenLIBModelforaBMSdevelopmentplatform.pdf` | BMS, measured/modelled data and equivalent-circuit behaviour | batteries | Valid; archive produced | Commercial-cell and pack groups were recovered, but evidence coverage was incomplete and the pack experiment had no output measurements. |
| `Application_of_First_Principles_Computations_Based.pdf` | Na-ion DFT/first-principles | batteries | Valid; archive produced | DFT and experimental comparison values were recovered, but cited review values were assembled as focal battery-performance experiments. |
| `coatings-16-00912.pdf` | Anode materials and high-entropy oxides; review stress test | batteries | Valid; archive produced | Extensive cited-literature extraction (21 materials, 33 performance points) contaminated the focal archive. |
| `applsci-10-04112.pdf` | Hard negative for “cycling” and “performance” | mechanical | Correctly rejected; battery extractor skipped | Correct domain behaviour. |

## Aggregate metrics

### Routing accuracy

- Classification result: 8/8 correct (100%).
- Seven documents were routed from normal extracted PDF text.
- The solid-state DRT/ML paper required a clearly labelled title-metadata fallback after PDF text extraction failed. Therefore normal end-to-end routing availability was 7/8 (87.5%), despite correct classification after fallback.
- The negative control routed to `mechanical`, not `batteries`.

### Schema-validation success

- Six Gemini extractions were attempted.
- Five passed strict Pydantic validation: 5/6 (83.3%).
- One failed strict validation: the NASA report used `paragraph` as an evidence source type in ten places.
- One battery paper never reached Gemini because PDF text extraction failed.
- Five canonical archives were produced from seven in-domain documents: 5/7 (71.4%).

The NASA failure is classified as a **prompt/schema-interface problem**, not a reason to relax arbitrary extras. `paragraph` has an unambiguous possible mapping to `text`, but that mapping should only be introduced deliberately, with a regression test, after the batch findings are reviewed. The current strict failure correctly prevents silent data loss.

### Extraction completeness

The archive completeness values for completed documents were:

| File | Structural completeness |
|---|---:|
| `batteries-11-00142.pdf` | 0.900 |
| `batteries-11-00011.pdf` | 1.000 |
| `Ziebert...pdf` | 0.857 |
| `Application_of_First_Principles...pdf` | 1.000 |
| `coatings-16-00912.pdf` | 0.600 |

Mean structural completeness was 0.871. This must not be interpreted as scientific accuracy: the DFT review scored 1.000 even though cited results were represented as focal experiments, and Li2FeTiO4 scored 0.900 despite zero evidence coverage and failed condition association for every manual gold point.

### Manual gold correctness

Only `batteries-11-00142.pdf` has an existing manual gold standard.

- Structural accuracy: 1.000
- Value accuracy: 1.000 (5/5 values recovered)
- Condition-association accuracy: 0.000 (0/5)
- Provenance coverage: 0.000 (0/5)
- Overall score: 0.500

The values `121.3 mAh/g`, `108.2 mAh/g`, `89.2%`, `1258.6 ohm`, and `1.096e-12 cm2/s` were recovered and assigned to the 700 °C material variant. However, the three cycling results were assigned `0.1 C` despite the documented `0.1 C` versus `1 C` contradiction, and none of the five points had evidence. The archive therefore contains the right values but does not establish scientifically safe facts.

### Condition-association correctness

- The Li2FeTiO4 strict gold conditions failed 5/5 checks.
- The Li2FeTiO4 extraction produced explicit association warnings but retained disputed C-rates in the performance points and archive.
- Five additional Li2FeTiO4 review candidates were detected: three retention values lacked cycle associations, and the charge-transfer resistance and diffusion coefficient lacked method associations.
- The anode review produced 15 condition-review candidates, primarily capacity values missing cycle or rate context. Four C-rate associations were already flagged by post-processing as unsupported by their attached evidence snippet.
- The original EIS and BMS documents did not trigger the generic condition-review rules, but no manual gold exists for those papers.

### Provenance coverage

Across the five validated documents, 86 of 164 evidence-capable records carried evidence: aggregate record coverage 52.4%.

| File | Records with evidence | Coverage |
|---|---:|---:|
| `batteries-11-00142.pdf` | 0/36 | 0.0% |
| `batteries-11-00011.pdf` | 8/9 | 88.9% |
| `Ziebert...pdf` | 5/9 | 55.6% |
| `Application_of_First_Principles...pdf` | 14/18 | 77.8% |
| `coatings-16-00912.pdf` | 59/92 | 64.1% |

Eighty-seven evidence snippets were emitted. After normalizing PDF typography and Unicode differences, 82/87 matched source text. Five remained non-verbatim or incorrectly localized: one EIS statement and four anode-review passages. One anode-review passage was associated with page 12 although the reported values occur on page 13. This is a provenance-quality issue even though the underlying values occur in the paper.

Sixty-nine of 87 snippets used `source_type="unknown"`. Evidence-type classification is therefore also weak.

### Unsupported or hallucinated facts

- All 68 extracted performance-point numerical/raw values could be found somewhere in their respective source text. No obvious invented numerical value was detected by this check.
- This does **not** establish support for the archived facts: Li2FeTiO4 produced 20 performance points with no attached evidence, and many review values lack focal/citation attribution.
- Five evidence snippets were not verbatim after robust normalization and require manual inspection.
- The DFT document contains a broken cross-reference: group `group_na2fe_fecn6` points to `mat_nafe_fecn6`, while the material ID is `mat_na2fe_fecn6`. Strict field validation does not currently enforce referential integrity.
- The EIS paper reports a likely source-table swap of NCM and plumbago anode/cathode labels. The extractor preserved the source wording and recorded the ambiguity rather than silently correcting it; this is correct scientific behaviour.

### Duplicate facts and experiment structure

- No duplicate performance-point signatures were found in the validated battery documents.
- No duplicate archive measurement signatures were found across experiments.
- In `batteries-11-00011.pdf`, internal resistance appeared only in the EIS experiment, not both EIS and general performance. The canonical EIS behaviour is working for this paper.
- `batteries-11-00142.pdf` did not extract an EIS protocol. Consequently, resistance, Warburg, and diffusion values remained in general performance experiments rather than a canonical EIS experiment. They were not duplicated, but their experiment classification is incomplete.
- Shared protocol reuse remained intact for Li2FeTiO4. No sample-specific protocol differences were lost in the observed output.

### Table/figure extraction limitations

- `1-s2.0-S2666386426002407-main.pdf` is a complete PDF-ingestion failure caused by an embedded-font structure rejected by PyPDF.
- Li2FeTiO4 table/figure values were recovered, but their evidence was entirely absent and the EIS protocol was missed.
- The original EIS paper successfully preserved six table-sourced evidence objects, showing that table-derived evidence can work when text extraction is clean.
- DFT Table 1 comparison values were recovered, but then suffered review/citation attribution problems.
- None of the successfully extracted inputs reached the 180,000-character truncation threshold, so these failures are not explained by prompt truncation.

### Cited-literature contamination

This is the clearest recurring cross-paper failure.

- The DFT perspective produced four material groups and ten performance points drawn from its comparison table. Although an extraction note correctly says these are compiled from cited literature, the archive represents them as `battery performance / cycling` experiments of the review paper.
- The anode review produced 21 material groups, 33 performance points, and 12 material synthesis records from cited studies. These were likewise assembled as focal experiments/processes.
- Across the two reviews, 43 cited performance measurements entered focal archives.

The problem is both a **prompt problem** and a **recurring representation/assembler gap**. The prompt says not to attribute cited work to the focal paper, but the available output/archive path has no explicit cited-study ownership mechanism and does not prevent review values from becoming focal experiments.

## Failure-pattern classification

| Pattern | Classification | Recurrence | Recommended disposition |
|---|---|---:|---|
| `source_type="paragraph"` rejected ten times in the NASA response | Prompt problem / bounded compatibility gap | One paper, ten fields | Do not allow arbitrary values. Consider explicitly prompting the enum or mapping only `paragraph -> text`, with regression tests. |
| PyPDF rejects dual `/FontFile` and `/FontFile3` | PDF extraction problem | One paper | Add a controlled fallback PDF parser; do not alter the battery schema. |
| Evidence arrays entirely empty for Li2FeTiO4 | Prompt problem plus validation gap | Severe in one paper; partial absence in four others | Make evidence requirements measurable and reject or downgrade unsupported quantitative facts. |
| Cited review results become focal experiments | Recurring schema/assembler gap and prompt problem | Both reviews | Define explicit cited-study ownership or omit cited quantitative records from focal archives. |
| Disputed C-rate retained despite conflict note | Prompt/guardrail problem and scientific ambiguity | Three gold cycling facts plus other Li points | Clear disputed conditions deterministically unless point-level evidence resolves them. Do not choose either rate. |
| DFT values assembled as cycling experiments | Recurring schema/assembler gap | All four DFT groups | Introduce correct computational experiment semantics without changing domain schema version merely for software versioning. |
| Material reference does not resolve | One-off LLM ID variation exposing semantic-validation gap | One DFT group | Add cross-reference validation; do not guess the intended material during validation. |
| Evidence snippet paraphrase or wrong page | One-off LLM formatting/provenance variation | Five of 87 snippets | Require verbatim/page-consistent evidence or downgrade the fact. |
| EIS protocol omitted from Li2FeTiO4 | Table/figure extraction limitation or prompt omission | One of two EIS-bearing validated papers | Collect more EIS papers before changing the schema; strengthen extraction/evidence handling if repeated. |

## Reliability recommendation

### Currently reliable enough to continue validation

- **Domain routing on extractable PDFs:** all seven normally extractable inputs were routed correctly, including the hard negative.
- **Canonical EIS placement in the focused original EIS paper:** measurements were not duplicated between general and EIS experiments, and provenance coverage was comparatively strong. This is promising, but one successful paper is insufficient for production reliability.

### Not currently scientifically reliable

- **Cathode materials synthesis:** value recovery is strong on Li2FeTiO4, but provenance and condition association failed completely in this run.
- **Anode materials:** only review evidence was tested, and cited-literature contamination was extensive.
- **Degradation/SOH:** the NASA paper failed schema validation, while Li2FeTiO4 retention conditions were not reliably associated.
- **DFT/first-principles:** values were extracted, but cited-result ownership, material references, and archive experiment semantics were unsafe.
- **Battery dataset/modelling:** BMS extraction completed, but NASA dataset extraction failed strict validation and BMS provenance was only 55.6%.
- **Review papers:** not reliable for canonical archive generation because cited work is represented as focal work.
- **General EIS/impedance:** the dedicated EIS paper performed well, but Li2FeTiO4 missed its EIS protocol and the DRT/ML paper could not be ingested. The subtype is not consistently reliable across the batch.

## Decision

Batteries V1 is **not yet ready for unattended multi-paper corpus extraction**. It is ready for another controlled iteration after addressing batch-level issues in this order:

1. PDF parser fallback for valid PDFs rejected by PyPDF.
2. Review-versus-focal ownership and DFT experiment semantics.
3. Mandatory/verifiable provenance for quantitative facts.
4. Deterministic removal of scientifically disputed condition associations.
5. Bounded handling or clearer prompting of the `paragraph` evidence-source alias.
6. Cross-reference integrity validation.

No schema or extraction fix was implemented during this run.
