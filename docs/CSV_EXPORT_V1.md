# Synthex CSV Export V1

CSV Export V1 is a deterministic, researcher-facing projection of a validated `SynthexArchive`.
The archive JSON remains the canonical record. Exporting CSV never re-runs extraction, calls a
provider, modifies the archive, or provides an import/reconstruction path back into the archive.

## Export modes

- `results.csv` is the default one-measurement/observation-per-row view. It contains only records
  already admitted to canonical archive collections.
- `results_all.csv` is created only when the researcher explicitly enables quarantined records.
  Every quarantined row is marked `admission_status=quarantined` and retains ownership, rejection
  reason, audit path, evidence summary, and deterministic JSON for the retained raw object.
- The CSV bundle contains stable-header tables for sources, materials, processes, experiments,
  calculations, measurements, relationships, and evidence. IDs are preserved or deterministically
  derived so joins remain inspectable. DFT/computational records stay in `calculations.csv` and are
  labelled `record_type=calculation` in the measurement view.

## Scientific and spreadsheet guarantees

- Missing values are empty cells; the exporter does not guess them.
- Raw values and numerical qualifiers such as `approx` are preserved alongside normalized values.
- Ownership, admission status, evidence origin, evidence strength, and estimated status are visible.
- Irregular nested metadata uses deterministic JSON-in-cell encoding.
- Text beginning with `=`, `+`, `-`, or `@` is escaped against spreadsheet formula injection;
  genuine negative numeric values and negative numeric-with-unit strings remain numeric text.
- Files are UTF-8 with a UTF-8 BOM by default for reliable scientific-symbol display in Windows
  spreadsheet software. Line endings are CRLF and ZIP entries are byte-for-byte deterministic.
- Empty archives and quarantined-only generic archives produce valid, stable-header exports.

## Python API

```python
from synthex_platform.export import (
    export_csv_bundle,
    export_csv_bundle_zip,
    export_results_csv,
)

results_bytes = export_results_csv(archive)
all_results_bytes = export_results_csv(archive, include_quarantined=True)
bundle = export_csv_bundle(archive)
zip_bytes = export_csv_bundle_zip(archive)
```

The primary Streamlit app exposes the same derived outputs under **Extract Paper → Export Results**
using the already-built archive held in session state.
