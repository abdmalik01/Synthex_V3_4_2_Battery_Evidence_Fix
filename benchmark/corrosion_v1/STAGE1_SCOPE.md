# Corrosion V1 — Stage 1 Scope

Status: **implemented as an offline schema/routing foundation; pending local regression verification**.

## Goal

Corrosion V1 gives Synthex a conservative, source-tracked representation for corrosion literature before any dedicated live Gemini extractor is enabled.

The Stage 1 objective is intentionally limited to:

1. domain ontology / manifest;
2. strict scientific schema;
3. deterministic routing and paper typing;
4. offline scientific guardrails and regression tests;
5. benchmark-corpus design.

No live Corrosion-specific Gemini extraction is claimed at Stage 1.

## Supported scientific scope

### Materials and treatments

- alloys and pure metals;
- substrates and working electrodes;
- coatings and conversion layers;
- passivation / surface treatments;
- inhibitors;
- surface preparation such as grinding, polishing, cleaning, degreasing and pickling;
- heat treatment where it materially changes corrosion state.

### Corrosive environments

- electrolyte / immersion medium;
- chloride concentration;
- pH;
- temperature;
- exposure / immersion duration;
- atmosphere where explicitly reported;
- flow or agitation where explicitly reported.

### Experimental methods

- potentiodynamic polarization;
- linear polarization resistance;
- EIS;
- immersion / weight-loss tests;
- salt-spray tests;
- localized / pitting-corrosion tests.

### Core performance / electrochemical properties

- corrosion rate;
- corrosion current density (`icorr`);
- corrosion potential (`Ecorr`);
- polarization resistance (`Rp`);
- charge-transfer resistance (`Rct`);
- solution resistance (`Rs`);
- CPE / double-layer-capacitance parameters;
- anodic / cathodic Tafel slopes;
- pitting, breakdown and repassivation potentials;
- inhibition efficiency;
- coating / protection efficiency;
- mass / weight loss;
- penetration or pit depth where explicitly reported.

### Computational corrosion

Stage 1 permits explicitly reported computational descriptors such as adsorption energy and work function, but they remain calculations rather than experimental corrosion measurements.

## Scientific guardrails

1. Never silently convert reported potentials between reference-electrode scales.
2. Never infer exposed geometric area merely from a current-density unit.
3. Never calculate corrosion rate from `icorr` unless a later explicit derivation contract provides all required inputs and uncertainty rules.
4. Keep EIS fitted parameters attached to the reported equivalent circuit and exposure condition.
5. Do not relabel `Rct` as `Rp` or vice versa without explicit source support.
6. Keep review, cited-prior-work, comparison-table, background and example values out of focal canonical results.
7. Keep DFT / molecular simulation in calculations.
8. Preserve conflicting environments, concentrations, reference electrodes and test conditions as unresolved conflicts.
9. Never silently repair ambiguous units, formulas or OCR corruption.
10. Quantitative values require source evidence before canonical admission in later stages.

## Initial benchmark design

The planned fixed Corrosion V1 corpus should contain 8 papers:

- **CORR-GOLD-A** — bare alloy, polarization-focused experimental paper;
- **CORR-COAT-B** — coating / surface-treatment paper;
- **CORR-INHIB-C** — corrosion-inhibitor paper;
- **CORR-EIS-D** — EIS-heavy paper with equivalent-circuit fitting;
- **CORR-WEIGHT-E** — immersion / mass-loss paper;
- **CORR-DFT-F** — computational corrosion / inhibitor-adsorption paper;
- **CORR-REVIEW-G** — review contamination control;
- **CORR-NEGATIVE-H** — non-corrosion materials paper for routing control.

## Stage 1 acceptance gates

Before Stage 2 begins:

- corrosion manifest loads through `DomainRegistry`;
- core properties and guardrails are present;
- clear corrosion papers route to `corrosion`;
- battery papers containing EIS do not get stolen by corrosion routing;
- paper typing is multi-label;
- strict schema rejects broken references;
- condition conflicts cannot be silently resolved;
- computational descriptors remain in calculations;
- all Stage 1 tests pass locally;
- full repository regression is green before a new baseline is recorded.

## Stage 2 preview

Stage 2 will add the dedicated Corrosion Gemini extraction boundary, evidence verification, canonical admission/quarantine rules and archive assembly. It should begin only after Stage 1 offline verification is green.
