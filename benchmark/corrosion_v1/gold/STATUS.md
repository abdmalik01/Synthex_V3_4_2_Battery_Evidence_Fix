# Corrosion V1 Stage 3 — Gold Review Status

This directory contains paper-level gold/control records created only after direct review of the locked benchmark PDFs.

| Paper | Role | Status | Record |
|---|---|---|---|
| CORR-GOLD-A | bare alloy / polarization + EIS | **manual source review complete** | `CORR-GOLD-A.json` |
| CORR-COAT-B | coating / surface treatment | **manual source review complete** | `CORR-COAT-B.json` |
| CORR-INHIB-C | inhibitor study | **manual source review complete** | `CORR-INHIB-C.json` |
| CORR-EIS-D | EIS-heavy study | **manual source review complete** | `CORR-EIS-D.json` |
| CORR-WEIGHT-E | immersion / weight loss | **manual source review complete** | `CORR-WEIGHT-E.json` |
| CORR-DFT-F | computational corrosion | **manual source review complete** | `CORR-DFT-F.json` |
| CORR-REVIEW-G | review contamination control | **manual source review complete** | `CORR-REVIEW-G.json` |
| CORR-NEGATIVE-H | non-corrosion routing control | **manual source review complete** | `CORR-NEGATIVE-H.json` |
| CORR-HOLDOUT-I | localized-corrosion holdout | **holdout; untouched for tuning until freeze** | — |

## Review decisions

### CORR-GOLD-A
Direct PDF review confirmed the material, NaCl environments, SCE reference electrode, potentiodynamic scan protocol, and exact EIS Table 2 values. Polarization quantities that appear only graphically are not plot-digitized into gold.

### CORR-COAT-B
Direct PDF review confirmed the 20# steel rusted substrate, TE-GAE coating variants, 3.5 wt % NaCl environment, and exact Tafel corrosion-current-density values. The focal paper does not explicitly state the reference electrode, so Ecorr is not scored. Coating resistance Rc is not relabeled as charge-transfer resistance.

### CORR-INHIB-C
Direct PDF review confirmed mild steel in 1 M HCl, SCE, 0.5 mV/s PDP, and method-specific Table 2 current-density/inhibition-efficiency values for CSQN and NSQN. A prose/table inhibitor-name ordering conflict is preserved explicitly; gold follows the labelled Table 2 rows rather than silently reconciling the prose.

### CORR-EIS-D
Direct PDF review confirmed P91 steel with ZrO2-3%molY2O3 coating in 60 wt.% NaNO3/40 wt.% KNO3 at 500 °C, the printed EIS perturbation/frequency conditions, and Table 2 Re/Rt values. Protective-layer resistance Rcp stays distinct from Rt. Author-estimated corrosion rate is source-tracked but is not used as a primary raw-EIS gold observation.

### CORR-WEIGHT-E
Direct PDF review confirmed mild steel in 1.0 M HCl with ETO. Primary gold uses the explicitly associated 500 ppm, 5 h, 303 K corrosion-rate and inhibition-efficiency pair. A separate concentration-sweep statement reports a different 500 ppm corrosion rate without the same uniquely explicit time association; the conflict is preserved and not silently reconciled.

### CORR-DFT-F
Direct PDF review confirmed a computational corrosion paper using DFT/MD for IB, MB and CV adsorption on Fe(110). Computational outputs are retained as calculations only. Experimental inhibition efficiencies cited from prior literature are not focal gold.

### CORR-REVIEW-G
The source is explicitly a review article. Expected focal canonical experiments are zero, and numerical examples from cited studies must retain review/cited-prior-work ownership.

### CORR-NEGATIVE-H
The source is a LiFePO4/C lithium-ion battery electrode paper. Expected route is `batteries`; EIS/Nyquist terminology must not cause corrosion routing.

### CORR-HOLDOUT-I
The uploaded source identity matches the localized-corrosion holdout. No tuning gold or numeric holdout assertions were created. It remains excluded until the fixed A–H benchmark is frozen.

## Stage 3 gate

The **manual source-review gate for the fixed eight-paper benchmark A–H is complete**. Next steps are offline gold-record regression checks, then a controlled live scored extraction of the fixed A–H corpus. The holdout remains excluded from tuning.

Last verified full repository regression before these documentation/gold-record additions: **303 passed, 2 warnings**.
