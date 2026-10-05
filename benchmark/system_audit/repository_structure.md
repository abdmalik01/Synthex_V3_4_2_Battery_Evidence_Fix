# Repository structure and conservative cleanup audit

Snapshot: release-readiness working tree after the additive pytest-output
cleanup, before any push. Git tracks 1,053 paths at this checkpoint. The
current checkout also contains unrelated modified/untracked scientific work;
this document describes the proposed tracked tree, not an assertion that the
primary directory is clean.

| Area | Role | Decision |
| --- | --- | --- |
| `synthex_platform/core`, `extraction`, `providers`, `storage`, `jobs.py`, `live_jobs.py`, `api.py` | Runtime, scientific contracts, provider isolation, persistence, durable jobs, API | Keep current stable module boundaries; no aesthetic moves. |
| `platform_app.py`, `streamlit_app.py`, `synthex_platform/ui_*` | Main UI and legacy gas-sensing UI | Keep entry points; improve read-only audit presentation in place. |
| `benchmark/<domain>_v1` | Locked corpora, gold, deterministic audits, provider-history summaries | Keep science paths stable. `benchmark/system_audit` holds cross-domain projections. |
| `tests_v3`, `tests`, `synthex_v2` | Current regression and legacy compatibility | Keep; do not merge suites without migration evidence. |
| `catalog`, `schemas`, `knowledge`, `docs` | Registries, archive contract, domain knowledge, developer guidance | Keep. |
| `extraction/` at root | Older extraction shim | Retain for compatibility; name overlaps `synthex_platform/extraction`. |
| `tmp/pdfs` tracked PNGs | Historical visual recovery illustrations/checkpoint evidence | Retain pending provenance review; do not assume disposable from path name. |
| `output/`, `.pytest_*/`, `data/jobs/`, archive locks | Runtime/provider/test data | Ignored; create lazily in runtime. Historical three pytest basetemp trees removed from Git index only. |

## Empty and low-content files

`git ls-tree -r -l HEAD` found **zero empty tracked files**. It found 26
two-byte JSON files, all `[]` candidate inventory/coverage outputs in dated
Catalysis checkpoints. Classification: **KEEP_REQUIRED** as historical
checkpoint evidence; a short array is not proof of an unused file. No
`__init__.py`, source lock, gold, freeze manifest, or provider record was
deleted. Untracked empties were not treated as Git release content.

## Empty directories

Git cannot represent a truly empty directory. In the primary working tree,
top-level `.pytest_corrosion_stage3`, `.pytest_run`, `.pytest_stage3`,
`.pytest_full_run`, and `.pytest_tmp` currently appear empty/inaccessible:
**runtime basetemp**, ignored, left on disk. `docs/rag` is an empty,
untracked folder: **UNKNOWN_REVIEW_REQUIRED** (possible planned extension),
left in place. No directory was physically removed. `output/` and many
additional `.pytest_*` directories are untracked local state, not inputs to
the proposed checkout.

A recursive check of the principal source/data/benchmark trees also found
empty local `data/benchmarks`, `data/graph`, `data/jobs`, and
`tmp/pdfs/biomaterials` directories. The first three are runtime destinations;
the last is temporary rendering space. All are absent from Git's committed
tree and were left untouched. Runtime code should create them on demand.

## Historical pytest artifacts

117 tracked files under three root basetemp directories were introduced in
earlier commits (the creation history includes `ca3c354`, `80f6791`, and
`745cab1`). They are generated per-test PDFs, JSON, PNG, CSV and JSONL; their
names mirror pytest's temporary test directories. No non-generated tracked
code/reference requires those exact paths. They were already shown missing
or permission-denied in the primary tree. The cleanup commit removes only
their Git index entries and adds `.pytest_*/` to `.gitignore`; existing local
files/directories were not deleted and history remains recoverable.

## Confusing areas still requiring deliberate follow-up

`benchmark/catalysis_v1/outputs/` contains tracked historical outputs with
local path strings; they may encode scientific provenance. Treat them as
historical source content, not runtime scratch, until references and hashes
are audited. The root `tmp/pdfs` tracked images likewise need a separate
evidence-retention decision. `tests/` and `tests_v3/` are intentionally
parallel. Primary-tree untracked Biomaterials files and provider artifacts
must be reviewed separately before claiming a portable scientific release.
No files were renamed or moved in this cleanup.
