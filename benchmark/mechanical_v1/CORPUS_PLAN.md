# Mechanical V1 controlled corpus plan

Status: offline foundation and fail-closed scorer implemented. No Mechanical source is locked,
no paper-derived gold assertions have been reviewed, and no provider run is authorized.

`gold_a_contract.json` is deliberately empty. To activate `MECH-GOLD-A`, independently review
one primary tensile paper, record its local filename and SHA-256, title/DOI, and explicit
assertions for each value, sample, processing state, temperature, strain rate, reported term,
scientific type, and evidence snippet. Set `status` to `locked_reviewed` only after review.
`score_gold_a.score_files(archive_path, contract_path, source_path)` verifies the source lock
before scoring an offline archive. The synthetic scorer test validates mechanics only; it is
not a substitute for a controlled paper benchmark. No Gemini run is ready at this stage.

The first corpus should stay small enough for assertion-level review while covering the
scientific boundaries that are most likely to contaminate a shared materials archive.

| Case | Paper profile | Contract exercised |
| --- | --- | --- |
| `MECH-GOLD-A` | Focal tensile study with multiple temperatures, orientations, or strain rates | Sample/process association; condition-resolved yield strength, UTS, elongation, and author-derived modulus; scalar evidence |
| `MECH-CREEP-B` | Creep and stress-rupture study with several stress-temperature pairs | Applied-stress/temperature association; creep strain-time series provenance; minimum creep rate and rupture time as reported derived metrics |
| `MECH-FATIGUE-C` | S-N or strain-life study with explicit R ratio and frequency | Joint stress-amplitude/cycles coordinates; run-outs versus failures; no invented S-N points or fatigue limit |
| `MECH-HARD-D` | Heat-treatment or processing comparison reporting two hardness methods/scales | Process lineage; Vickers/Rockwell/Brinell separation; no cross-scale conversion |
| `MECH-FRACTURE-E` | Fracture-toughness or crack-growth study | K/J/CTOD identity; fracture-toughness units distinct from stress; da/dN-Delta-K series provenance |
| `MECH-COMPUTE-F` | Constitutive, finite-element, or ML mechanical prediction paper | `CalculationRecord` separation; model predictions never admitted as experimental measurements; reported validation data remain experimental |
| `MECH-REVIEW-G` | Mechanical-properties review containing comparison tables | Cited/review ownership quarantine; no canonical contamination from literature summaries |
| `MECH-NEGATIVE-H` | Adjacent-domain paper using generic stress/strain/load/failure language without a focal mechanical test | Negative routing; domain boundary with additive manufacturing, corrosion, batteries, biomaterials, and semiconductors |

Source-locking criteria for a later phase:

- lawful local PDF access and stable checksum;
- machine-readable text or tables for the primary gold assertions;
- explicit sample and condition associations;
- at least one deliberately tempting value that must be quarantined;
- independent human review of every gold value, unit, condition, ownership, evidence locator,
  and scientific type before any live provider benchmark.
