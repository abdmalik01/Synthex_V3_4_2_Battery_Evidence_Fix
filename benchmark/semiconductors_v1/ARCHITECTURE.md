# Semiconductors V1 — eight-case scientific closure

The first four cases use publisher PDFs locked by SHA-256, manually adjudicated gold written before deterministic recovery, and PDF-table parsers that do not read gold to produce candidates. `source_lock_*.json` records the DOI, publisher URL, PDF hash, gold hash, decisive tables and pages. `interim_audit.py` checks parsed cells against gold and audits the assembled canonical archives. This is not a freeze manifest.

## Model and scientific boundaries

The canonical `MaterialEntity` is the film material, while `DeviceEntity(device_type="semiconductor_thin_film")` is the specimen. Its ordered layers contain a separate substrate and semiconductor film. `ProcessStep` carries growth/annealing/tempering conditions and creates material/device lineage. `ExperimentRecord` carries measured or source-reported derived outputs; `CalculationRecord` is reserved for later computational work. The specimen and process identities remain visible in archive relationships and namespaced analytics lineage.

The semiconductor manifest and contract distinguish electronic/optical gaps, PL peaks, work function, electron affinity, ionization energy, carrier/dopant densities, mobility, conductivity, bulk resistivity, sheet/contact resistance, voltage/field, current density, and film thickness. A Tauc/squared-absorption gap requires a derivation basis. Hall mobility requires the Hall method. Source-scaled table units are retained, and only five explicitly checked scale conversions are provided for the current corpus. A missing measurement temperature remains missing. Nominal dopant at.% is composition context, not cm^-3 dopant or carrier density. A dash is not zero.

## First four cases

| Case | Primary paper/table | Scientific stress |
| --- | --- | --- |
| SEM-GOLD-A | Ponja et al., 2020, Table 2, doi:10.1038/s41598-020-57532-7 | Four Ga:ZnO films; carrier concentration, Hall mobility, bulk resistivity, sheet resistance and Tauc optical gap with scaled units. |
| SEM-TRANSPORT-B | Wang et al., 2015, Table 2, doi:10.1186/s11671-015-0801-y | Twenty Al:ZnO growth/ambient/doping states; 14 unavailable cells remain absent; 46 exact transport outputs. |
| SEM-OPTICAL-C | Sun et al., 2022, Tables 1–3, doi:10.3390/ma15207373 | Sapphire absorption-gap specimens are distinct from Si PL specimens; M2 composition differs by Si orientation. |
| SEM-PROCESS-D | Yang et al., 2015, Table 1, doi:10.1038/srep15001 | Ten F:SnO2 tempering rows in two series, including the repeated 700°C/220 s reference; Hall coefficient and crystallite size. |

The four closure cases add computational band gaps, review containment, photovoltaic cross-domain routing, and measured/calculated LE-FET results. Do not infer unreported values or provider evidence.

| Case | Locked source | Canonical outputs | Record boundary |
| --- | --- | ---: | --- |
| SEM-COMPUTE-E | Primary AlSb monolayer DFT/GW paper, doi:10.1038/s41598-023-37081-5 | 12 | Twelve calculation records; no experiment records. Missing SOC GW cells remain absent. |
| SEM-REVIEW-F | Explicitly labeled 2D TFET review, doi:10.1038/s41699-022-00352-2 | 0 | Publisher review label and authors' self-description both required; two cited/review values quarantined. |
| SEM-NEG-G | Primary perovskite solar-cell paper, doi:10.3390/en13030585 | 0 | Photovoltaic route, zero Semiconductor archive/analytics/graph records. |
| SEM-MIXED-H | Primary perovskite LE-FET paper, doi:10.1038/ncomms8383 | 9 | Five measured transport/EL outputs in two experiments, four DFT masses in one calculation; substrate, film, device and processing remain distinct. |

The machine-readable `closure_audit.json` passes 40/40 invariants across eight cases: 120 canonical outputs, 49 experiments, 13 calculations, and zero ownership, evidence, cross-record, analytics or graph contamination. `freeze_manifest.json` records every source title, DOI, locked source and gold hash, case counts, individual provider run hashes/scores, discovery provenance, regression evidence, and reproduction commands. The manifest is generated only after the full test suite and diff checks pass.

## Known interim limits and live gate

- The first four cases are all thin films; the mixed LE-FET extends device and DFT coverage, but does not benchmark every wafer, heterojunction, defect, or work-function path.
- SEM-GOLD-A's Table 2 does not explicitly state its Hall measurement temperature; its 450°C growth temperature is not copied into that field.
- SEM-OPTICAL-C's reported absorption coefficient header uses `cm^-2`; it is excluded rather than silently corrected to the usual `cm^-1`.
- SEM-PROCESS-D's figure-only resistivity/mobility are not digitized. Its calculated emissivity is out of this gold scope.
- The offline `interim_audit.json` deliberately does not assess provider qualification. After explicit Semiconductor-source egress approval, exact Gemini IDs were discovered and four controlled runs were performed on SEM-GOLD-A and SEM-TRANSPORT-B. `live_gate.json` preserves the original history: `SEM_LIVE_GATE_SATISFIED` is true because hash-verified raw payloads are scientifically scoreable. Versioned, append-only normalization reshapes explicit provider content into schema-valid candidates, but no run has provider-supplied page-verbatim evidence sufficient for canonical admission. Raw value and property-key scores are unchanged. OpenAI remains future-supported but inactive.

Offline reproduction: `python -m benchmark.semiconductors_v1.interim_audit`, `python -m benchmark.semiconductors_v1.closure_audit --write`, and `python -m pytest tests_v3 -q --basetemp=.pytest_tmp_semiconductor_closure` (using the repository `.venv` interpreter). No network or provider call is required.
