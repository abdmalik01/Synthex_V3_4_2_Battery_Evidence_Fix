# Corrosion V1 Stage 3 — Gold Review Status

This directory contains paper-level gold records created only after direct review of the locked benchmark PDFs.

| Paper | Role | Status | Record |
|---|---|---|---|
| CORR-GOLD-A | bare alloy / polarization + EIS | **manual source review complete** | `CORR-GOLD-A.json` |
| CORR-COAT-B | coating / surface treatment | **manual source review complete** | `CORR-COAT-B.json` |
| CORR-INHIB-C | inhibitor study | pending manual source review | — |
| CORR-EIS-D | EIS-heavy study | pending manual source review | — |
| CORR-WEIGHT-E | immersion / weight loss | pending manual source review | — |
| CORR-DFT-F | computational corrosion | pending manual source review | — |
| CORR-REVIEW-G | review contamination control | pending manual source review | — |
| CORR-NEGATIVE-H | non-corrosion routing control | pending manual source review | — |
| CORR-HOLDOUT-I | localized-corrosion holdout | **untouched until freeze** | — |

## CORR-GOLD-A decision

Direct PDF review confirmed the material, NaCl environments, SCE reference electrode, potentiodynamic scan protocol, and exact EIS Table 2 values. The polarization section discusses and plots corrosion potential, corrosion current density and pitting potential, but does not print exact scalar values for those quantities in a table or in the prose. Therefore no plot-digitized values are admitted as gold. Exact scored numeric observations are taken only from explicitly printed EIS Table 2 values with their NaCl concentration associations.

## CORR-COAT-B decision

Direct PDF review confirmed the 20# steel rusted substrate, TE-GAE coating variants, 3.5 wt % NaCl electrochemical environment, and exact Tafel Table 1 corrosion-current-density values for untreated steel and all four TE:GA ratios. The focal paper does not explicitly state the reference electrode; therefore its printed Ecorr values are retained in the source review record but are not scored as potential gold. The EIS circuit defines Rs as electrolyte resistance and Rc/Cc as coating resistance/capacitance; Rc is not relabeled as charge-transfer resistance, and no exact fitted Rc table is printed. No protection efficiency is derived from Icorr.

Current repository regression baseline before live Corrosion Stage 3 extraction: **303 passed, 2 warnings**.
