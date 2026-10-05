# Synthex release-candidate review notes

These notes describe the `research-metadata-only` branch. It is a publication
of code and scientific metadata, **not** the binary benchmark corpus or a
claim that a clean clone can replay every source-byte check. The development
`main` history stays local because it contains the TE-GOLD-A supplementary
PDF blob.

## Scope

- Added Mechanical, Additive Manufacturing, Photovoltaics, Thermoelectrics,
  Membranes, and Semiconductors V1 scientific contracts, source/gold identities,
  closure-audit metadata, and frozen-scope records. Newly introduced publisher
  corpus binaries are not distributed in this branch.
- Added provider-independent multi-model extraction, provider audit
  infrastructure, durable resumable jobs, a read-only cross-domain system
  audit, and operator recovery safeguards. Provider output remains separate
  from canonical scientific admission. Focal-work evidence and ownership checks
  gate canonical measurements; uncertain content remains quarantined.
- Hardened source tracking, append-only archive/job persistence, external
  action journaling, and reconciliation of uncertain provider/search actions.
- Added Biomaterials V1 deterministic scientific closure and offline
  reproduction. Biomaterials has 8 cases, 158 canonical outputs, and 40/40
  deterministic invariants in the current audit, but its live-provider gate is
  pending and the domain is **not frozen**. Recorded no-payload runs have
  unavailable scores, not 0%.
- Stopped tracking generated pytest basetemp trees and added repository
  organization, reproducibility, and dependency documentation. Historical
  optional raw provider bodies are local-only; offline replay uses committed
  scientific metadata and locally verified source bytes, not ignored `output/`
  files.

## Known limitations and release gate

- Nine domains are reported frozen within their stated scopes; the older
  Batteries and Catalysis metrics are not standardized for cross-domain
  counts. Gas-sensing V2 is separate from the ten-domain audit.
- Some historical Catalysis metadata contains developer-machine sidecar
  references, but clean replay does not dereference them. New path metadata
  should remain portable.
- No newly introduced PDF, workbook, or ZIP blob is included. The historical
  review of six large local PDFs, including the rights-uncertain Nature
  Materials TE-GOLD-A supplement, remains in
  [the file-level review](docs/SOURCES_AND_LICENSES.md). Full source-byte
  verification needs independently acquired copies matching the locks.
- Local primary checkout contains unrelated, uncommitted research/provider
  work. Corpus-independent tests must pass in a clean checkout; full closure
  needs the separately verified local corpus. Do not stage local-only files.

No provider or search calls, scientific gold edits, or tag are part of this
metadata packaging. This branch does not carry the unpublished development
history containing the supplement.
