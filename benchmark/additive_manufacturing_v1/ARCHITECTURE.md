# Additive Manufacturing V1 architecture decision

## Decision

AM V1 is a process-centric domain with hybrid process-plus-property coverage. It reuses the
generic Synthex archive (`MaterialEntity`, `ProcessStep`, `ExperimentRecord`,
`CalculationRecord`, `Relationship`, and `DomainPayload`) rather than introducing a separate
AM archive model.

Feedstock and parts are materials. AM builds and post-processing are ordered process steps with
explicit inputs and outputs. Density, porosity, defect, surface, melt-pool, microstructure, and
productivity values are experiment outputs. Mechanical values from AM papers retain Mechanical
V1 property identities and unit-family admission rules. Analytics reuse the existing canonical
archive projection and add unambiguous source-backed build coordinates through process lineage.

## Repository audit before AM V1

The repository already had:

- an `additive_manufacturing.yaml` manifest with a small LPBF-oriented vocabulary;
- lexical router terms for additive manufacturing, LPBF/SLM, scan speed, and hatch spacing;
- generic draft models and archive assembly for materials, processes, experiments, calculations,
  evidence, and relationships;
- generic `processed_by`/`tested_in` lineage and analytics enrichment from process parameters;
- generic ownership and source-evidence gating.

The repository did not yet have:

- AM-specific property roles, unit families, or scientific-type admission;
- separation of linear, surface, and volumetric energy-density identities;
- an explicit relative-density versus porosity guard;
- a strong method-plus-parameter/output router context rule;
- distinct process input/output material references for Feedstock -> Build -> Post-processing;
- reuse of the Mechanical admission contract for mechanical outputs in AM papers;
- a source-locked AM benchmark, deterministic recovery, scorer, or AM safety tests.

## Scientific boundaries

- Generic parameter language such as “laser power” and “scan speed” is insufficient to route AM.
  A recognized AM process plus AM parameters or outputs is required for a strong route.
- Only source-reported process parameters and outputs enter canonical records. The system does not
  calculate volumetric, surface, or linear energy density from other coordinates.
- Linear (`J/mm`), surface (`J/mm2`), and volumetric (`J/mm3`) energy density have different unit
  families and cannot substitute for one another.
- Relative density and porosity remain distinct properties. Neither is computed as the complement
  of the other.
- Review, background, and cited-prior-work objects remain quarantined from focal canonical data.
- Post-processing is represented as a separate process step and is not folded into build parameters.
- Every admitted AM parameter/result requires focal ownership, an allowed scientific type, a
  compatible unit family, and value-specific verbatim evidence with a page and locator.

## First benchmark rationale

AM-GOLD-A uses a primary, open-access LPBF tungsten study (DOI 10.3390/ma14010165). Its Table 1
contains 27 clean focal rows joining laser power, scan speed, hatch spacing, and measured relative
density. The method pages additionally report powder D10/D50/D90, machine, argon atmosphere,
oxygen threshold, preheat temperature, layer thickness, scan strategy, rotation angle, measurement
method, replicate count, and post-build handling. This makes it a compact but high-value test of
the full process-coordinate-to-result path without inventing derived quantities.
