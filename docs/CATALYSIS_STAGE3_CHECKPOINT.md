# Catalysis V1 Stage 3 checkpoint status

Catalysis V1 Stages 1 and 2 are complete and the fixed seven-paper Stage 3 benchmark has been implemented and historically executed. Candidate-recovery logic is also implemented. Catalysis is **not Stage-4-ready yet** because the final Gold A checkpoint and one final seven-paper confirmation remain unresolved.

The final Gold A checkpoint must use the historical benchmark model `gemini-3.5-flash` in pinned benchmark mode. Production model failover must not be used for this scientific confirmation.

The two required native-prose Gold A associations are:

- `MMONiCo` → CO2 methanation → CO2 conversion `~80 %` at `350 °C`, preserving the approximation qualifier.
- `MMONiFe` → CO2 methanation → CO2 conversion `50 %` at `350 °C`.

Recent checkpoint attempts reached the provider but received Gemini `503 UNAVAILABLE / high demand` before a primary JSON response. Such runs are **PROVIDER_BLOCKED**, not scientific failures: no schema repair, candidate coverage interpretation, admission decision, or Gold scoring can occur without the primary model response.

Use `python run_catalysis_gold_a_checkpoint.py` for future retries. The helper writes each attempt to a fresh timestamped directory under `benchmark/catalysis_v1/outputs/`, preserves historical artifacts, and emits `checkpoint_status.json` with an explicit execution classification.

If Gold A passes, the next actions are: run focused Catalysis tests, run the full repository suite, then perform exactly one final seven-paper confirmation with the same pinned `gemini-3.5-flash`. Only after that should Stage 4 readiness be decided. Do not begin Stage 4 automatically.
