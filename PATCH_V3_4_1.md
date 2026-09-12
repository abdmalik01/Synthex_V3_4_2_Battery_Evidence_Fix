# Synthex V3.4.1 — Battery Schema Hardening

This patch hardens Batteries V1 against JSON-shape variation observed during the Li2FeTiO4 benchmark.

Key changes:
- retries Gemini 503 ServerError responses with exponential backoff and jitter
- coerces numeric synthesis step labels to strings
- accepts compact/legacy shared protocol strings without validation failure
- preserves and maps alternate Gemini keys such as `voltage_window`, `cycle_count`, `loading`, `drying`, `pressing`, `dimensions`, `format`, `glovebox_atmosphere`, `o2_limit`, and `h2o_limit`
- splits equipment strings into a list
- parses two-stage drying text where explicit temperatures/times are present
- canonicalizes battery performance property labels (specific capacity, retention, Rct, diffusion coefficient, Warburg coefficient, etc.)
- strengthens the prompt to distinguish cyclic voltammetry from constant-voltage charging
- forbids silent repair of typos or ambiguous OCR strings
- tightens condition-to-performance association rules

Validation: `python -m pytest -q` -> 22 passed.
