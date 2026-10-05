# Mechanical V1 controlled corpus plan

`MECH-GOLD-A` is source-locked and independently reviewed: the official publisher PDF
`corpus_pdfs/metals-08-00393.pdf` and 18 Table 4 assertions in `gold_a_contract.json`
are pinned by `source_lock.json`. The six tensile condition rows distinguish alloy,
heat treatment, overaging, and test temperature. Room temperature remains `RT`.
`recover_table4.py` extracts source-word geometry with no hardcoded result values;
`run_gold_a_offline.py` scores this deterministic recovery independently of Gemini.

Two earlier controlled `gemini-3.5-flash` Gold-A runs each returned no payload after
three same-model `provider_unavailable` attempts. The authorized closure retry returned
a payload on its first attempt. All eight raw scientific objects were quarantined and
raw full-gold remains 0/18; deterministic source recovery remains 18/18. Do not present
offline recovery as a provider result or change the frozen gold to fit output.

`MECH-CREEP-B` locks the publisher PDF and 24 reviewed Table 2 cells. Deterministic
recovery passes 24/24 and excludes all three `N/A` rows. Its one live call returned a
large semantic payload, but neither the raw nor schema-repair response validated;
the frozen raw payload is scored without canonical admission. Offline structural
normalization salvages all 41 explicit measurements without inventing values or evidence,
but canonical admission remains 0/24 because the provider supplied table IDs without
page, cell text, or complete locators. Deterministic source recovery remains 24/24.

`MECH-FATIGUE-C` locks the publisher PDF and 20 reviewed assertions selected from
Tables A1/A2. Deterministic recovery preserves all 60 tests and keeps 19 run-outs
censored. It passes 20/20 offline. After three earlier transient-unavailable attempts,
the closure retry returned a frozen schema-invalid payload. Raw full-gold is 0/20 and
deterministic recovery remains 20/20.

`MECH-HARD-D` locks the official Metals 2021 publisher PDF and all 18 Table 4
Micro-Vickers mean/uncertainty cells across three steels and six cooling rates.
Deterministic recovery passes 18/18. The first controlled live payload reproduced all 18
numeric cells but omitted required association/evidence details; raw full-gold and canonical
scores are 0/18 while deterministic recovery remains 18/18.

`MECH-FRACTURE-E` locks the official Materials 2021 publisher PDF and all 27 Table 6
fracture-toughness cells. Deterministic recovery passes 27/27 while preserving valid
`K_IC`, conditional J-integral-derived `K_JC`, and invalid rough `K_JU` identities. The
first live extraction payload was frozen; its one schema repair hit daily quota. The raw
payload scored 0/27 full assertions (4/27 value-unit matches), while deterministic
recovery remains 27/27.

`MECH-COMPUTE-F` locks a primary CASTEP/DFT study and 28 reviewed elastic-property
assertions across four computed phases. It produces four `CalculationRecord` objects,
28 outputs, and zero experiments. The authorized live call was rejected by the daily
request quota before a payload, so raw quality is unavailable rather than zero.

`MECH-REVIEW-G` locks the publisher-labelled Materials 2020 review and uses a two-signal
whole-document guard: publisher article type plus author self-description. A reviewed
prior-study hardness value remains visible in noncanonical review context; canonical
experiments, calculations, analytics rows, and graph edges are all zero. Offline score:
11/11. No provider call was made.

`MECH-NEGATIVE-H` locks an open-access Cell Reports Physical Science battery study that
contains stress, strain, failure, fracture, and resistance language. Repeated routing is
deterministically Batteries, with zero Mechanical records or contamination. Offline
score: 10/10. No provider call was made.

The first corpus should stay small enough for assertion-level review while covering the
scientific boundaries that are most likely to contaminate a shared materials archive.

| Case | Paper profile | Contract exercised |
| --- | --- | --- |
| `MECH-GOLD-A` | Focal tensile Table 4 | Sample/process association; condition-resolved yield strength, UTS, and elongation; scalar evidence |
| `MECH-CREEP-B` | Creep and stress-rupture study with several stress-temperature pairs | Applied-stress/temperature association; creep strain-time series provenance; minimum creep rate and rupture time as reported derived metrics |
| `MECH-FATIGUE-C` | S-N or strain-life study with explicit R ratio and frequency | Joint stress-amplitude/cycles coordinates; run-outs versus failures; no invented S-N points or fatigue limit |
| `MECH-HARD-D` | Three spring steels, six cooling rates, Table 4 Micro-Vickers results | Process lineage; Vickers identity; load/indent count; no cross-scale conversion |
| `MECH-FRACTURE-E` | OCHN3MFA steel in four heat-treatment states, Table 6 fracture toughness | `K_IC`/`K_JC`/`K_JU` identity and validity; fracture-toughness units distinct from stress |
| `MECH-COMPUTE-F` | CASTEP/DFT elastic constants and moduli for AuIn2-derived phases | `CalculationRecord` separation; C11/C12/C44 and moduli remain distinct; no experimental records |
| `MECH-REVIEW-G` | Mechanical-properties review containing comparison tables | Cited/review ownership quarantine; no canonical contamination from literature summaries |
| `MECH-NEGATIVE-H` | Adjacent-domain paper using generic stress/strain/load/failure language without a focal mechanical test | Negative routing; domain boundary with additive manufacturing, corrosion, batteries, biomaterials, and semiconductors |

All eight cases are now source-locked. Closure requires:

- lawful local PDF access and stable checksum;
- machine-readable text or tables for the primary gold assertions;
- explicit sample and condition associations;
- at least one deliberately tempting value that must be quarantined;
- independent human review of every gold value, unit, condition, ownership, evidence locator,
  and scientific type before any live provider benchmark;
- all 30 closure invariants passing with zero ownership, evidence, cross-record, or analytics contamination.
