# Photovoltaics V1 architecture and benchmark plan

## Audit

Synthex already provided a generic `DeviceEntity`, device references on experiments,
archive reference validation, and a small Photovoltaics manifest. It did not provide a
draft device/layer-stack representation, device assembly, PV-specific scientific
admission, guarded routing, or device-aware analytic context. Photovoltaics V1 extends
those shared primitives instead of introducing an incompatible archive.

## Canonical chain

`material -> ordered device layer -> device -> fabrication process -> experiment -> result`

Layer order and functional role are both preserved. Material identity never substitutes
for layer role: the same material may legally occupy different roles in different devices.
Every canonical experimental PV result is linked to exactly one admitted device and keeps
its illumination, irradiance, protocol, uncertainty, and value-specific source evidence.
Unreported active area, scan direction, temperature, or stability conditions remain
explicitly unreported; they are never inferred from other measurements.

## Eight-case closure matrix

| Case | Scientific purpose | Primary guard |
|---|---|---|
| PV-GOLD-A | Device performance across fabrication variants | 4 devices, 20 table values, conditions and uncertainties |
| PV-SPEC-B | EQE/IPCE spectral series | wavelength-coordinate preservation |
| PV-STAB-C | Operational and shelf stability | aging protocol, time, atmosphere, retention semantics |
| PV-STACK-D | Architecture and processing | ordered layer roles and source-reported fabrication lineage |
| PV-COMPUTE-E | Device/first-principles computation | predictions remain distinct from reported measurements |
| PV-REVIEW-F | Review article | non-focal values are quarantined |
| PV-NEG-G | Cross-domain hard negative | photocatalysis language cannot false-route to PV |
| PV-MIXED-H | Mixed device/processing/performance/spectral/stability study | modality and device associations remain explicit |

All eight cases are source-locked and pass deterministic recovery. The original four are:

- PV-GOLD-A: four CMP variants, 20 performance outputs with reported uncertainties.
- PV-SPEC-B: three device-specific Fig. 3b EQE series, 223 official workbook points.
- PV-STAB-C: six 85 °C ISOS-D-2 T80 variants and one reported 5072 h retention point.
- PV-STACK-D: six ordered PC70BM thickness/doping variants and 24 performance outputs.

The four closure additions are:

- PV-COMPUTE-E: five SCAPS-1D variants and 20 explicitly computational outputs.
- PV-REVIEW-F: an explicit two-signal review with cited values preserved noncanonically.
- PV-NEG-G: a photocatalysis paper that routes repeatably to Catalysis with no PV records.
- PV-MIXED-H: two processing variants with device-linked performance, EQE-integrated
  current, stabilized output, and thermal-retention measurements.

`closure_audit.py` checks all eight cases, 35 scientific invariants, analytics safety,
and the four contamination counters. All closure recovery is deterministic and
provider-free. The locked PV-GOLD-A and PV-SPEC-B live reports remain
`LIVE_UNAVAILABLE_AFTER_RETRIES` after three provider-side 503 responses; they are not
zero scores and are not rerun by the closure audit.
