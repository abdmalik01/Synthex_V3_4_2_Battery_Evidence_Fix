# Catalysis V1 Stage 3 — Gold A Provider-Available Checkpoint (2026-09-14)

## Outcome

**GOLD A CHECKPOINT: PROVIDER BLOCKED**

The bounded live checkpoint invoked the existing `CAT-GOLD-A` pipeline once. Gemini returned
`503 UNAVAILABLE` during the primary structured-extraction request because the configured model
was experiencing high demand. No valid primary JSON was returned, so schema repair and candidate
coverage recovery were correctly not invoked.

## Execution ledger

- benchmark: `CAT-GOLD-A`
- source: `1-s2.0-S0360319924005640-main.pdf`
- extraction status: `pipeline_error`
- primary calls: 1
- schema-repair calls: 0
- candidate-coverage calls: 0
- total Gemini calls: 1
- Serper/web calls: 0
- seven-paper corpus rerun: no
- Stage 3 extraction or scientific rules changed: no
- historical Stage 3 reports, summaries, and ledgers overwritten: no

Isolated machine-readable artifacts are under
`benchmark/catalysis_v1/outputs/provider_checkpoint_20260914/`.

## Scientific checkpoint

The provider failure occurred before a schema-valid extraction existed. Consequently this run
could not verify the Gold A target associations for MMONiCo (~80% CO₂ conversion at 350 °C) and
MMONiFe (50% at 350 °C), their `approx` semantics, or native evidence. It is an external
availability result, not a scientific or architectural failure, and it does not authorize Stage 4.
