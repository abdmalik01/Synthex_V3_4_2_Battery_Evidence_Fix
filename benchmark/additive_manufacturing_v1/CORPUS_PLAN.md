# Additive Manufacturing V1 corpus plan

AM V1 is process-centric: feedstock and build coordinates are represented as material/process
lineage, while density, defect, microstructure, surface, and reused Mechanical properties remain
measured experiment outputs. Reported derived quantities are allowed only when printed by the source.

## AM-GOLD-A

- Primary source: Li et al., *Laser Powder Bed Fusion of Pure Tungsten: Effects of Process
  Parameters on Morphology, Densification, Microstructure*, Materials 14 (2021) 165,
  DOI 10.3390/ma14010165, CC BY 4.0.
- Locked PDF: `corpus_pdfs/materials-14-00165.pdf`.
- Reviewed evidence: feedstock on page 2; build method on page 3; Table 1 and
  post-build handling on page 4.
- Gold scope: all 27 focal Table 1 specimens with laser power, scan speed, hatch spacing,
  shared reported build context, and measured relative density.
- Guardrails: no inferred energy density; relative density is not converted to porosity;
  each output retains one specimen and one process coordinate; post-processing remains a
  separate process step; all canonical values require page/cell or section evidence.
- Live status: one primary-credential `gemini-3.5-flash` attempt returned a payload and one
  schema repair was attempted. Both shapes were schema-invalid, so the raw result is recorded
  as unscorable rather than as zero percent. The deterministic recovery remains 27/27.

## AM-DENS-B

- Primary source: Zheng, Peng, and Wang, *Defect Analysis of 316 L Stainless Steel Prepared by
  LPBF Additive Manufacturing Processes*, Coatings 11 (2021) 1562,
  DOI 10.3390/coatings11121562, CC BY 4.0.
- Locked PDF: `corpus_pdfs/coatings-11-01562.pdf`.
- Gold scope: all nine Table 2 process-coordinate rows joined to all nine Table 4 Archimedes
  relative-density values; source-reported volumetric energy density is retained.
- Guardrails: relative density is not converted to porosity or absolute density; defect
  identities remain distinct; missing orientation is not inferred.
- Live status: one primary-credential `gemini-3.5-flash` attempt plus one schema repair. The
  payload is schema-invalid and canonically unscorable, but its preserved raw scientific content
  matches all nine process-coordinate, density, and lineage associations. Deterministic recovery
  is 9/9.

## AM-MICRO-C

- Primary source: Feng et al., *Impact of Heat Treatment and Building Direction on Selective
  Laser-Melted 316L Stainless Steel: Microstructure and Mechanical Properties*, Materials 18
  (2025) 32, DOI 10.3390/ma18010032, CC BY 4.0.
- Locked PDF: `corpus_pdfs/materials-18-00032.pdf`.
- Gold scope: 16 orientation/heat-treatment conditions and 80 Table 3 relative texture
  coefficients. The 12 heat treatments are separate post-process nodes.
- Live status: three allowed primary attempts were made. The first two returned 503 and the
  third returned a payload whose schema repair was unavailable (503). The raw scientific audit
  is preserved separately; canonical admission remains blocked. Deterministic recovery is 16/16.

## AM-MECH-D

- Primary source: De Terris et al., *Analysis of As-Built Microstructures and Recrystallization
  Phenomena on Inconel 625 Alloy Obtained via Laser Powder Bed Fusion (L-PBF)*, Metals 11 (2021)
  619, DOI 10.3390/met11040619, CC BY 4.0.
- Locked PDF: `corpus_pdfs/metals-11-00619.pdf`.
- Gold scope: three Table 1 AM build conditions joined to 12 Table 4 specimen/test conditions and
  36 canonical Mechanical outputs (yield strength, ultimate tensile strength, elongation).
- Live status: the first two primary attempts returned 503; the third returned a payload and one
  separately preserved schema repair. Neither is canonically valid. Deterministic recovery is
  12/12 with 36/36 Mechanical outputs.

## AM-POST-E

- Primary source: Chae et al., *Optimization of Aging Temperature and Heat-Treatment Pathways
  in Additively Manufactured 17-4PH Stainless Steel*, Materials 16 (2023) 7557,
  DOI 10.3390/ma16247557, CC BY 4.0.
- Locked PDF: `corpus_pdfs/materials-16-07557.pdf`.
- Gold scope: eight AM orientation/treatment states from Table 4 and 24 Mechanical outputs
  (yield strength, ultimate tensile strength, and elongation), joined to the DED context in
  Table 2. Direct aging and solid-solution-plus-aging remain distinct directional process
  lineages; the as-built states receive no post-process node.
- Live status: the first primary attempt returned a payload and one separately preserved repair;
  neither is canonically valid. The raw audit retains all yield and ultimate-strength values but
  not the eight elongations. Deterministic recovery remains 8/8 with 24/24 Mechanical outputs.

## AM-COMPUTE-F

- Primary source: Stavropoulos et al., *A Computationally Efficient Multi-Scale Thermal
  Modelling Approach for PBF-LB/M Based on the Enthalpy Method*, Metals 12 (2022) 1853,
  DOI 10.3390/met12111853, CC BY 4.0.
- Locked PDF: `corpus_pdfs/metals-12-01853.pdf`.
- Gold scope: the Ti6Al4V and SS316L Table 1 process coordinates joined to the Table 3
  predicted melt-pool widths and experimental validation context.
- Guardrails: predictions are `CalculationRecord` outputs with `simulation_result` scientific
  type; measured widths remain validation context and never become experiment outputs.
- Status: deterministic offline recovery is 2/2 with zero accidental `ExperimentRecord`
  promotion. No live call is authorized in this task.

## AM-REVIEW-G

- Review source: Bidulsky et al., *Coated Metal Powders for Laser Powder Bed Fusion (L-PBF)
  Processing: A Review*, Metals 11 (2021) 1831, DOI 10.3390/met11111831, CC BY 4.0.
- Locked PDF: `corpus_pdfs/metals-11-01831-v2.pdf`.
- Gold scope: explicit publisher `Review` label plus the authors' independent overview
  self-description; three cited-study numeric candidates retain their source evidence.
- Guardrails: cited-study materials, experiments, and values are review-owned and noncanonical;
  they produce no focal experiment, calculation, analytics, or graph records.
- Status: deterministic offline control is 11/11 with zero ownership or evidence violations.

## AM-NEGATIVE-H

- Negative source: Hou et al., *Synthesis of Cathode Material Li2FeTiO4 for Lithium-Ion
  Batteries by Sol-Gel Method*, Batteries 11 (2025) 142, DOI 10.3390/batteries11040142,
  CC BY 4.0.
- Locked PDF: `corpus_pdfs/batteries-11-00142-negative.pdf`.
- Negative scope: a primary battery-material paper containing the misleading surface terms
  `powder`, `layer`, `porosity`, `density`, `thermal`, `surface`, and `scan`.
- Guardrails: routing requires focal AM process evidence rather than vocabulary alone.
- Status: two deterministic routes select Batteries; the control is 10/10 with zero AM build,
  experiment, calculation, metric, analytics, or graph contamination.

## Eight-case closure

- The final audit covers all eight locked cases and 30 scientific invariants, provider-artifact
  integrity, ownership/evidence containment, cross-record leakage, Mechanical interoperability,
  and archive/analytics safety.
- Freeze scope is deterministic AM V1 only. Raw Gemini output remains separately scored and is
  not declared production-ready unless it passes canonical schema and evidence admission.

## Planned breadth

Later cases should cover PBF-EB/EBM, WAAM, binder jetting, and dedicated surface outputs. The
current corpus covers LPBF, DED, explicit post-processing, defect/microstructure outputs,
AM-plus-Mechanical testing, computational PBF-LB/M, review containment, and a non-AM control.
