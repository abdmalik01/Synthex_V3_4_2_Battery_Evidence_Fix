# Catalysis / Electrocatalysis V1 — Stage 4 Freeze Contract

Status: **freeze candidate; requires local regression confirmation before final closure**.

Stage 4 is deliberately a hardening/freeze stage. It does not authorize new scientific extraction behavior merely to improve benchmark scores.

## Frozen scientific boundary

Catalysis V1 supports:

- heterogeneous / thermal catalysis;
- electrocatalysis;
- catalyst synthesis and characterization;
- kinetics where explicitly reported;
- stability, deactivation and regeneration;
- computational catalysis / DFT as calculations;
- review/dataset ownership recognition.

Deferred from V1:

- homogeneous catalysis;
- photocatalysis as a dedicated extraction subtype;
- enzymatic / biocatalysis;
- full microkinetic-model extraction;
- automatic reaction balancing;
- active-site inference;
- automatic cross-normalization;
- automatic canonical admission of digitized curves.

## Frozen safety rules

1. Review, cited-prior-work, comparison-table, background and example values are never focal experiments.
2. DFT outputs remain calculations and never become experimental performance measurements.
3. Ag/AgCl, SCE, SHE, RHE, Hg/HgO and Hg/Hg2SO4 potentials are not silently converted.
4. `mA cm-2` does not establish geometric-area normalization by itself.
5. Product-specific FE, selectivity, partial current density and product-formation rate require product identity.
6. WHSV and GHSV are distinct.
7. TOF requires a reported site basis for defensible normalization.
8. Digitized graph data remain estimated/non-canonical unless a future explicit admission contract is introduced.
9. Missing or conflicting conditions remain missing/conflicted; Synthex does not choose a convenient value.
10. Scientific extraction behavior is changed only for a demonstrated defect, not to chase benchmark points.

## Frozen benchmark contract

The fixed seven-paper Stage 3 corpus remains the Catalysis V1 acceptance set:

- Gold A: heterogeneous experimental;
- Gold B: electrocatalysis;
- Compute C: pure DFT;
- Stability D: stability/deactivation;
- Review E: review contamination control;
- Photo F: deferred photocatalysis boundary;
- Negative G: non-catalysis routing control.

Acceptance remains:

- Gold A metric association 8/8;
- Gold B metric association 4/4;
- Gold B normalization-source review 2/2;
- Compute C PASS;
- Stability D PASS;
- Review E PASS;
- Photo F PASS under deferred-subtype policy;
- Negative G PASS;
- zero review contamination into focal canonical records;
- zero DFT leakage into experiments;
- zero unsupported potential conversion;
- zero digitized canonical leakage;
- zero referential-integrity failures.

## Change-control rule

After Stage 4 closure, modifications to Catalysis V1 scientific behavior require all of:

1. a reproducible defect or new explicitly approved scope requirement;
2. an offline regression test that fails before the fix;
3. the smallest scientifically conservative change;
4. focused Catalysis tests passing;
5. full repository regression passing before the freeze baseline is updated.

UI wording, provider resilience, batch orchestration, export presentation and other platform-level changes may continue as long as they do not alter these scientific semantics.

## Closure gate

Stage 4 can be marked **COMPLETE AND FROZEN** only after the current repository state passes the full local regression suite. Until then, this document defines the freeze contract but does not claim a new green baseline.
