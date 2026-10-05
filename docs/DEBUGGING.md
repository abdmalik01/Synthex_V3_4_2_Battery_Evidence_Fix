# Local debugging and offline replay

Run from the repository root with the intended virtual environment. On
Windows, use `.venv\Scripts\python.exe` explicitly; the `python` command may
be a non-runnable Microsoft Store alias. Install with
`.venv\Scripts\python.exe -m pip install -r requirements.txt` in a newly
created environment. The root `.env` is optional for offline checks and must
never be committed.

## First checks

```powershell
.venv\Scripts\python.exe -m pytest tests_v3 -q --basetemp=.pytest_tmp_local
.venv\Scripts\python.exe -m benchmark.semiconductors_v1.closure_audit
git diff --check
git status --short
```

Choose a fresh ignored `--basetemp` for concurrent or repeated runs. Some
historical test directories became inaccessible on Windows and are no longer
tracked; they are not fixtures. `output/`, `.pytest_*/`, `data/jobs/`, and
archive lock files are local runtime state. Do not copy them into a clean
checkout to make a test pass.

## Trace a record

Start with a case ID, source ID, job ID, or run ID. For scientific evidence,
find `benchmark/<domain>_v1/` source locks, the locked PDF/data, gold,
closure audit, and freeze manifest. Recompute the source hash and compare it
with the lock before investigating an extraction mismatch. Do not edit a gold
file to make a replay pass. Historical raw provider payloads may exist only
under ignored `output/<domain>/provider_runs/`; their audit summaries remain
separate from deterministic closure. An unavailable local raw artifact is not
a zero score and must not be fabricated.

For jobs, inspect the read-only **Developer · System audit → Jobs** view or
`GET /v1/system/jobs`; the default event journal is
`data/jobs/events.jsonl`. A `WAITING_PROVIDER` or
`RECONCILIATION_REQUIRED` state with uncertain external intent must be
reconciled against the external outcome before any retry. Operator controls
require developer mode and explicit `SYNTHEX_OPERATOR_ACTIONS_ENABLED=true`;
do not toggle them merely to clear a warning. JSONL recovery uses the
append-only event journal and `storage/atomic_jsonl.py`; preserve original
bytes and lock files while diagnosing corruption.

The Streamlit UI is `platform_app.py`; the API is
`synthex_platform/api.py`. The audit projection is
`synthex_platform/system_status.py` and reads
`benchmark/system_audit/*.json`. Missing or malformed audit artifacts should
show *Unavailable*, not a fabricated green status. Provider setup is
optional for offline imports/tests. Avoid `smoke_gemini.py`, live benchmark
runners, search, and UI actions that request external data when validating a
secret-free checkout.

If a path works only in the original developer directory, inspect metadata
for absolute `C:\Users\...` references. Portable semiconductor
`artifact_run_root` values are repository-relative and resolved by
`resolve_run_artifact_root`; ignored provider artifacts are not required for
ordinary clean-checkout imports or deterministic lock tests.
