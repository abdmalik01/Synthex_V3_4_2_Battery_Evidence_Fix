# Synthex Batteries V1 Validation Corpus Review

## Corpus summary

The user-supplied ZIP contains 19 PDFs. SHA-256 comparison identifies two duplicate pairs, leaving 17 unique documents. Two unique files are negative controls rather than battery literature, leaving 15 unique battery-relevant documents.

### Primary A/A+ benchmarks

1. **batteries-11-00142.pdf** — *Synthesis of Cathode Material Li2FeTiO4 for Lithium-Ion Batteries by Sol–Gel Method*. Original electrode-materials research. This is the primary A+ benchmark because it contains material synthesis, process variants, electrode fabrication, CR2032 assembly, electrochemical testing, cycling performance and EIS-derived transport metrics.
2. **batteries-11-00011.pdf** — Original EIS characterization/modeling study across temperature and SOC. Strong benchmark for EIS conditions and model/measurement linkage.
3. **1-s2.0-S2666386426002407-main.pdf** — Original solid-state battery EIS/DRT + machine-learning study. Strong benchmark for diagnostic features and ML-ready derived datasets.
4. **Evaluation_of_Li_Ion_Batteries.pdf** — NASA battery dataset analysis. Regression test for domain routing, grouped devices, repeated protocols, degradation statements and EIS ranges.
5. **ZiebertEEVC2017ATable-drivenLIBModelforaBMSdevelopmentplatform.pdf** — BMS/equivalent-circuit modeling and validation. Useful for model parameter records and measurement/model relationships.
6. **Application_of_First_Principles_Computations_Based.pdf** — DFT perspective/review. Useful for computational-descriptor vocabulary and for ensuring values from cited studies are not mistaken for focal original calculations.

### Secondary B benchmarks

The cathode/anode/SIB/solid-state review papers are valuable for ontology coverage, aliases, table extraction and review-vs-original-result discrimination, but should not be used as the main field-level extraction accuracy set because they aggregate results from many cited studies.

### Exclusions / negative controls

- `applsci-10-04112.pdf` is cycling biomechanics, not batteries. It is a useful hard-negative domain-router test because the word "cycling" occurs frequently.
- `Electrolytes - StatPearls - NCBI Bookshelf.pdf` is a biomedical/general electrolyte reference, not a battery paper. It is another negative-routing test.
- `battery_test.pdf` duplicates `Evaluation_of_Li_Ion_Batteries.pdf`.
- `Characteristics_and_properties_of_anode_materials_ (1).pdf` duplicates `Characteristics_and_properties_of_anode_materials_.pdf`.

## Primary electrode-materials benchmark: batteries-11-00142.pdf

This paper exposes the main gap in the earlier Batteries V1 schema. A research-useful extraction must represent the complete chain:

**Li2FeTiO4 composition → sol–gel synthesis → calcination variant → electrode formulation/coating → CR2032 assembly → electrochemical protocol → capacity/EIS/transport outputs.**

Gold assertions include:

- Li2FeTiO4 cathode synthesized by sol–gel.
- Citric acid / lithium acetate dihydrate / ferrous chloride tetrahydrate / titanium butoxide precursor system in anhydrous ethanol.
- 24 h stirring at room temperature; 65 °C water bath for 5 h; vacuum drying at 120 °C for 24 h; Ar precalcination at 500 °C for 8 h; secondary calcination variants at 600/700/800 °C.
- Electrode: 80 wt% active material + 10 wt% acetylene black + 10 wt% PVDF in NMP; Al foil; doctor blade; 1.0 mg cm−2 loading; 80 °C/12 h vacuum drying; 10 MPa pressing; 10 mm disks; 120 °C/6 h final drying.
- CR2032 cell; lithium foil; Celgard 2400 separator; 100 µL commercial lithium electrolyte; Ar glovebox with O2 and H2O each <0.1 ppm.
- CV: 0.1 mV s−1 over 1.5–4.8 V; 1 C = 300 mA g−1; rate capability 0.1 C–5 C; 100-cycle stability at 1 C.
- 700 °C sample: 121.3 mAh g−1 first discharge capacity, 108.2 mAh g−1 100th discharge capacity, 89.2% retention, Rct 1258.6 Ω, Li+ diffusion coefficient 1.096×10−12 cm2 s−1.

The precursor molar-ratio string is text-extraction-ambiguous in the PDF; Synthex should preserve its raw string rather than silently repair it.

## Why this corpus is useful

This is not yet a statistically large benchmark, but it is diverse enough to test five important failure modes: domain confusion, review-vs-original attribution, repeated-protocol duplication, true process→property linkage, and heterogeneous experimental/computational battery records. It should be expanded later with more original electrode-material papers, electrolytes, solid electrolytes, sodium-ion systems, full cells, degradation studies and original first-principles studies.
