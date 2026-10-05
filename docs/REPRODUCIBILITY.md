# Offline scientific reproducibility

Synthex separates scientific replay from the availability of historical live-provider bodies. This metadata-only branch does not distribute newly introduced third-party corpus PDFs, source-data workbooks, or ZIP files. A clean checkout can inspect locks, gold, audits, and run corpus-independent tests; **full source-byte and closure replay first requires the exact local source files named by those locks**. Neither path requires a Gemini, OpenAI, or search call or the developer's ignored `output/` tree.

`benchmark/omitted_binary_manifest.json` records path, byte count, and SHA-256
for 55 omitted binaries from the local scientific candidate. Check every
independently obtained file against its identity before using it for replay.
The TE-GOLD-A supplementary PDF was already excluded from that candidate and
is identified separately below. The manifest is an identity inventory, not
a permission statement or a bulk download instruction.

## Artifact classes

| Class | Examples | Clean-checkout policy |
|---|---|---|
| Authoritative scientific artifacts | Publisher PDFs/source data, source locks, gold JSON, frozen manifests | Locks, gold, and manifests are committed. Newly introduced publisher binaries are not; acquire them independently and verify their recorded SHA-256 before full replay. |
| Reproducible derived artifacts | Offline case reports, closure audits, provider indexes | Read a committed deterministic snapshot, or rebuild with the locally verified source bytes; do not require a pre-existing ignored `output/` copy. |
| Historical provider metadata | Exact provider/model/run IDs, attempts, payload status, raw hashes, scores, schema and admission outcomes in freeze manifests and `benchmark/provider_audit/provider_history.json` | Committed as metadata; no models are merged and no absent payload is scored as zero. |
| Optional raw provider evidence | Immutable response bodies and validation/normalization output under `output/` | Local-only. If present, the recorded hash must match; if absent, report `RAW_PROVIDER_ARTIFACT_AVAILABLE = false` and `NOT_AVAILABLE_LOCALLY`. Absence is not corruption or a scientific replay failure. |
| Local operational state | Jobs, locks, caches, pytest basetemp, UI/export output | Ignored; not a scientific prerequisite. |

The historical provider outcome and a currently available raw body are different claims. A frozen deterministic case can remain scientifically reproducible when the body is absent. A body that is present but has the wrong hash is a validation failure. Neither condition changes source gold or silently promotes a provider response to canonical data. No-payload outcomes retain an unavailable scientific score (`null`/N/A), never `0%`.

TE-GOLD-A's Nature Materials supplementary PDF is distributed as a
[publisher link](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41563-021-01064-6/MediaObjects/41563_2021_1064_MOESM1_ESM.pdf)
and SHA-256 (`7f3f950c6e2385622056cfd49481edca38cd0e40234f2dc3ef84dc112a9d05de`),
not repository bytes. The frozen gold and source lock still identify it. Without a local copy,
`supplementary_local_status` reports `not_available_locally`; offline recovery requires the
article and both source-data workbooks as well as gold. This is historical provenance,
**not** present-tense verification of missing PDF or workbook bytes.
For full local source-byte verification, independently download the 46-page publisher PDF to
`benchmark/thermoelectrics_v1/corpus_pdfs/TE-GOLD-A_supplementary.pdf`; its hash and page
count must match or recovery fails. The path is ignored to prevent accidental staging.

Biomaterials V1 is **deterministically closed, not frozen**. Its live-provider gate is false: the recorded BIO-GOLD-A attempts returned no payload, and BIO-BIOACT-B was not transmitted. The pending manifest must not be read as a live-provider pass.

## Offline checks

From the repository root, with dependencies installed **and the required local
corpus restored and SHA-256-verified**:

```powershell
python -m pytest tests_v3 -q --basetemp=.pytest_tmp
python -m benchmark.biomaterials_v1.closure
```

The first command exercises the frozen replay contracts and read-only system status. The second verifies Biomaterials' eight source/gold locks, exact deterministic outputs, forty scientific invariants, and compact provider history without making a provider call. Without local source files, missing-source failures are expected and must not be reported as a scientific score or silently skipped. The pytest basetemp is disposable after the run.

Historical Catalysis `visual_sidecar_reference` values inside committed run snapshots may contain developer-machine paths. They are provenance text, not paths that clean-checkout replay opens. New source-sidecar capture uses paths in the current checkout; a missing historical sidecar does not authorize inventing source evidence.
