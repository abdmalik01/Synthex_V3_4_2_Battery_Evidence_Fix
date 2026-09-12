# Synthex V3.4.2 — Battery Process Evidence Fix

This patch fixes a real Gemini-output compatibility issue discovered while benchmarking the Li2FeTiO4 cathode paper.

## Fixed
- `BatteryProcessStep.evidence` now supports a list of evidence objects (the natural research-grade representation).
- Backward compatibility remains for a single evidence object or a string.
- The archive assembler now carries all step-level evidence into process records and uses the first passage only when a single measurement needs one primary provenance reference.
- Prompt rules now forbid inventing numeric room temperature values, forbid treating `water bath`/`oven`/`furnace` as an atmosphere, and strengthen handling of conflicting electrochemical conditions.
- Added regression tests for evidence-array validation and archive assembly.

## Important scientific observation from the benchmark paper
The Li2FeTiO4 paper itself contains potentially conflicting rate-capability/cycling descriptions in different sections. Synthex should preserve such conflicts rather than silently choosing one condition.
