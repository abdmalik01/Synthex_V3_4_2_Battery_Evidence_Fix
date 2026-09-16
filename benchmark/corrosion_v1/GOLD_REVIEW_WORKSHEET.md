# Corrosion V1 — Manual Gold Review Worksheet

Status: **manual source review required; this file is not itself gold**.

This worksheet turns the locked Stage 3 scaffold and offline candidate bundle into a paper-by-paper review sequence. It must be completed by checking the actual local PDF. Candidate snippets are navigation aids only and must never be promoted to gold without direct PDF verification.

## Non-negotiable annotation rules

- Record only values explicitly printed in the focal paper.
- Preserve the paper's printed unit exactly; do not pre-convert units.
- Preserve the reported reference electrode exactly for corrosion, pitting, repassivation, or breakdown potentials.
- Preserve experiment/material/environment/treatment associations.
- Record PDF page number and a short exact supporting snippet.
- Do not promote review citations, comparison-table values, or cited prior work to focal gold.
- Do not infer missing units, normalization bases, exposed areas, equivalent circuits, or reference-electrode conversions.
- DFT/computational outputs remain calculations, never experimental performance.
- `CORR-HOLDOUT-I` stays untouched until after the fixed eight-paper benchmark is frozen.

## Review sequence

### CORR-GOLD-A — bare alloy / potentiodynamic polarization

File: `Corrosion 1.pdf`  
DOI: `10.20964/2020.01.26`

Candidate navigation hints from the offline bundle: methods/reference electrode around PDF page 2; potentiodynamic/pitting discussion around page 4.

Verify and record:

- focal material identity and role;
- NaCl environment/concentrations and any deaeration/immersion conditions needed for association;
- reference electrode exactly as printed;
- scan rate exactly as printed;
- at least one `corrosion_potential` observation if explicitly tabulated/reported;
- at least one `corrosion_current_density` observation if explicitly tabulated/reported;
- at least one `pitting_potential` observation if explicitly reported;
- page + exact evidence snippet for each scored observation.

Do not derive a corrosion rate from current density.

### CORR-COAT-B — coating / surface treatment

File: `Corrosion 2.pdf`  
DOI: `10.1021/acsomega.2c00172`

Candidate navigation hints: corrosion-current result appears in the abstract/page 1 and polarization section/pages 4–5; equivalent-circuit discussion is around page 5.

Verify and record:

- substrate identity;
- treatment/coating identity and TE:GA ratio association;
- relevant surface/preparation context;
- `corrosion_current_density` with exact unit;
- `charge_transfer_resistance` only if the paper explicitly reports that quantity with a clear circuit/element meaning;
- `protection_efficiency` only if explicitly reported and clearly associated;
- equivalent circuit and exposure condition where needed for an EIS quantity;
- page + exact evidence snippet.

Do not silently equate coating resistance, polarization resistance, and charge-transfer resistance.

### CORR-INHIB-C — inhibitor study

File: `Corrosion 3.pdf`  
DOI: `10.1016/j.heliyon.2020.e03939`

Candidate navigation hints: inhibitor/environment summary on page 1; gravimetric and electrochemical details around pages 3–4.

Verify and record:

- mild-steel material identity;
- 1 M HCl environment;
- inhibitor identity (NSQN/CSQN as applicable);
- inhibitor concentration for every scored efficiency/current-density value;
- temperature where required for association;
- `inhibition_efficiency` with exact printed value/unit;
- `corrosion_current_density` with exact printed value/unit;
- any DFT outputs kept in calculations rather than experiments;
- page + exact evidence snippet.

### CORR-EIS-D — EIS-heavy study

File: `materials-16-00546-v2.pdf`  
DOI: `10.3390/ma16020546`

Candidate navigation hints: EIS equipment, amplitude and frequency range around page 4; CPE/equivalent-circuit discussion around page 5; fitted circuit values around page 6.

Verify and record:

- material/coating identity;
- molten-salt environment and test temperature/exposure time;
- frequency range exactly as printed;
- perturbation amplitude exactly as printed;
- equivalent-circuit interpretation;
- one or more `charge_transfer_resistance`/transfer-resistance values only if the paper's element semantics support that property;
- `solution_resistance` if explicitly identifiable;
- `cpe_parameter` values with their printed unit/indices and exposure-time association;
- page + exact evidence snippet.

Do not rename circuit elements merely to fit the ontology; preserve source semantics first.

### CORR-WEIGHT-E — immersion / weight-loss study

File: `Corrosion 5.pdf`  
DOI: `10.1016/j.sajce.2022.06.011`

Candidate navigation hints: methods and immersion durations around page 2; corrosion-rate and inhibition-efficiency results around page 3.

Verify and record:

- mild-steel material identity;
- 1.0 M HCl environment;
- ETO inhibitor concentration;
- immersion/exposure time;
- temperature;
- `corrosion_rate` exactly as printed, including unit;
- `mass_loss` only where a direct focal numeric value is explicitly reported;
- `inhibition_efficiency` exactly as printed;
- page + exact evidence snippet.

Do not recompute corrosion rate from weight loss for gold.

### CORR-DFT-F — computational corrosion

File: `Corrosion 6.pdf`  
DOI: `10.1155/2013/175910`

Verify and record:

- paper type as computational corrosion;
- Fe(110) surface association;
- inhibitor/dye/adsorbate identity;
- DFT method/functional/software only if explicitly reported;
- explicit computational outputs such as adsorption energy, HOMO/LUMO-related descriptors, or other reported quantities;
- page + exact evidence snippet.

Required safety assertion: **no computational output may be admitted as experimental corrosion performance**.

### CORR-REVIEW-G — review contamination control

File: `Corrosion 7.pdf`  
DOI: `10.3390/polym14122306`

Candidate navigation hints: the paper identifies itself as a review on page 1; cited coating-performance examples appear throughout, including early review discussion and salt-spray examples.

Verify:

- paper type is review;
- expected canonical focal experiments = 0;
- cited numeric results remain review/cited-prior-work ownership and never become focal gold.

No numeric focal-gold values should be created from this paper.

### CORR-NEGATIVE-H — non-corrosion routing control

File: `Corrosion 9.pdf`  
DOI: `10.20964/2018.09.30`

Candidate navigation hint: page 1 clearly identifies LiFePO4/C cathode material, lithium-ion batteries, charge/discharge cycling, EIS/Nyquist language.

Verify:

- expected route = `batteries`;
- must not route to `corrosion`;
- EIS/Nyquist vocabulary alone is insufficient evidence for corrosion ownership.

No corrosion gold observations should be created from this paper.

## Completion record

For each scored paper, change the corresponding `gold_status` in `gold_assertions_scaffold.json` only after every populated assertion has been checked directly against the PDF.

Suggested statuses:

- `pending_manual_source_review`
- `manual_source_review_in_progress`
- `manual_source_review_complete`

The fixed eight-paper benchmark may proceed to a live scored extraction only when all eight scored papers have a resolved gold/rejection contract, offline scorer/corpus tests are green, and the full repository regression remains green.

Current verified repository baseline before manual gold completion: **303 passed, 2 warnings**.
