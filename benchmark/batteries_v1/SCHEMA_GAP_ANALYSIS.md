# Batteries V1 → V1.2 Schema Gap Analysis

## What the earlier extractor could represent

The previous battery schema handled source metadata, battery groups, chemistry/cathode/anode/electrolyte labels, temperature, charge/discharge/EIS protocols, measured variables, generic performance points and evidence. This worked well for the NASA dataset-analysis paper.

## What it could not represent well

The Li2FeTiO4 electrode-materials paper contains research-critical information that had no dedicated home: precursor lists, synthesis steps, process sequence, calcination variants, electrode formulation fractions, solvent/current collector/coating method, mass loading, drying/pressing, cell assembly, separator, electrolyte volume, glovebox limits, CV scan rate, voltage window, C-rate definition and common protocols shared by several material variants.

## Changes in V1.2

- Added `materials[]` and `BatterySynthesis`.
- Added ordered `BatteryProcessStep` records.
- Added `ElectrodeFabrication`.
- Added `CellAssembly`.
- Added `ElectrochemicalTesting`.
- Added document-level `shared_protocols[]` and group-level `protocol_refs[]`.
- Added deterministic post-processing that promotes repeated charge/discharge/EIS protocols to shared records even if Gemini repeats them.
- Added `material_ref`, `variant_label` and `calcination_temperature` on groups.
- Expanded performance points with `method` so EIS/Warburg-derived properties retain method provenance.
- Added quantity normalization in the archive assembler.
- Reworked quality scoring so provenance and normalization are measured from actual scientific records rather than only a narrow set of child measurements.
- Added subtype-aware battery completeness scoring; a dataset-analysis paper and a materials-synthesis paper are judged against different expected fields.
- Added semantic warnings when an electrochemical-performance paper has no quantitative performance points or a synthesis paper has no structured material record.

## Remaining gaps after V1.2

- Figure digitization is not yet implemented; numerical curves that exist only in plots remain inaccessible.
- Table extraction still relies on PDF text quality and Gemini interpretation rather than a dedicated table parser.
- Original DFT battery papers need a dedicated `BatteryCalculation`/atomistic schema rather than only generic performance points.
- Electrolyte formulations need a richer composition schema (salt, solvent mixture, concentration, additives).
- Full-cell pairing, N/P ratio, areal loading on both electrodes and balancing should be added for advanced cell studies.
- Uncertainty/error bars and replicate counts need explicit fields.
