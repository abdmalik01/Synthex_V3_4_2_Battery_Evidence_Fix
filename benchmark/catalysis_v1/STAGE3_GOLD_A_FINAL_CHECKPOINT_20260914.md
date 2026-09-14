# Catalysis V1 Stage 3 - Gold A Final Checkpoint (2026-09-14)

## Model selection

The saved Stage 3 run summaries identify `gemini-3.5-flash` as the model used for successful
scientific benchmark runs. The current `.env` configuration is `gemini-3.6-flash`. Historical
execution artifacts, rather than the current environment, therefore selected `gemini-3.5-flash`
for the authoritative Gold A checkpoint.

## Availability matrix

Each model received exactly one minimal request: `Reply with exactly: GEMINI WORKS`. No paper
content or Gold A data was sent during availability testing.

| Model | Status | Returned text / provider response | Latency |
| --- | --- | --- | ---: |
| `gemini-3.5-flash` | AVAILABLE | `GEMINI WORKS` | 78.135 s |
| `gemini-3.6-flash` | AVAILABLE | `GEMINI WORKS` | 1.925 s |
| `gemini-3.7-flash` | 503 / provider capacity | Model experiencing high demand | 0.959 s |
| `gemini-3.8-flash` | 503 / provider capacity | Model experiencing high demand | 19.173 s |

## Authoritative Gold A outcome

**GOLD A CHECKPOINT: PROVIDER BLOCKED**

The unchanged Stage 3 pipeline was invoked once with the historical model through a temporary
process-level override. The full scientific primary request returned `503 UNAVAILABLE` before a
valid extraction existed.

- primary scientific calls: 1
- schema-repair calls: 0
- candidate-coverage calls: 0
- scientific provider failures: 1
- Serper calls: 0
- web calls: 0
- `.env` modified: no
- historical reports, summaries, or ledgers overwritten: no
- seven-paper confirmation: not run because the Gold A gate did not pass

The run could not evaluate either required native-prose association:

- MMONiCo -> CO2 methanation -> CO2 conversion -> ~80 % -> 350 °C
- MMONiFe -> CO2 methanation -> CO2 conversion -> 50 % -> 350 °C

The checkpoint is an external provider-capacity result, not evidence of a repository or scientific
architecture defect. Catalysis is not yet a candidate for Stage 4 confirmation.

Machine-readable outputs are isolated under
`benchmark/catalysis_v1/outputs/gold_a_final_checkpoint_20260914/`.
