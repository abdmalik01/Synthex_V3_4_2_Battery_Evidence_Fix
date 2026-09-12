# Migration from Synthex V2.1 to V3

V3 is additive: the current `synthex_v2/`, `streamlit_app.py`, legacy `extraction/llm_extractor.py`, visualization code, and gas-sensing benchmark remain untouched.

## What moves into V3

| V2 concept | V3 equivalent |
|---|---|
| `SensorRecord` | `SynthexArchive` + `gas_sensing` domain payload |
| paper metadata | `sources[]` |
| sample | `materials[]` |
| synthesis/deposition | `processes[]` |
| testing conditions + performance | `experiments[]` |
| ab initio fields | `calculations[]` |
| evidence snippets | `Evidence[]` attached to measurements/records |
| visualization-specific tables | benchmark builders derived from canonical archive |

## Migration rule

Do not delete V2 records. Write a converter that maps every V2 `SensorRecord` into a V3 archive, validate it, then compare the derived visualization tables before switching the default UI.

## Recommended next implementation

`synthex_platform/migrations/v2_sensor.py` should be added after a representative set of V2 JSON outputs is available for regression testing.
