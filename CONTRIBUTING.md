# Contributing to Synthex

Create a branch from the reviewed base; install `requirements.txt` in a fresh
virtual environment. Run focused tests while developing. The full `tests_v3`
suite requires locally verified source binaries omitted from this branch;
run it with a local, ignored `--basetemp` before proposing a scientific change.
Record interpreter and dependency versions when a clean checkout fails.

Keep commits narrow. Stage explicit paths (`git add -- path...`), inspect
`git diff --cached`, and never use `git add .` in a dirty research worktree.
Do not commit `.env`, credentials, local provider responses, archives, job
journals, caches, or pytest output. Redact secret-shaped diagnostics without
removing synthetic redaction-test coverage.

Locked PDFs/source data, gold, source locks, closure audits, frozen manifests,
and raw provider evidence are scientific records. Any scientific change needs
separate review, hash verification, deterministic closure, and clear case-level
provenance. Never silently improve a gold answer or promote a no-payload run
to 0%. A live provider/search call needs specific user authorization for its
source, provider, exact model, attempt bound, and audit persistence. Offline
tests and replay must make no external inference/search calls.

Before release, review introduced Git object sizes, publisher distribution
rights, staged secret/path scans, `git diff --check`, and a truly clean
checkout. Do not push, rebase, or rewrite history as a side effect of cleanup.
