# CODEX_HANDOFF.md

# Synthex — Codex Handoff

## 1. Project identity

**Project:** Synthex  
**Current development line:** V3.4.2  
**Current focus:** Visual Intelligence V1 closure; Batteries V1 frozen
**Long-term goal:** Build a materials-intelligence platform that converts scientific literature into structured, provenance-aware, machine-usable datasets linking:

**process → structure/material → computation → property → performance**

Synthex is not intended to be only a PDF extractor. The target is a reusable research platform that can support experimental and computational materials data, benchmarking, graph relationships, queryable archives, and eventually multiple materials-science domains.

---

## 2. Current domain roadmap

Synthex currently has one mature vertical and one actively maturing vertical:

1. **Gas sensing** — live and relatively mature
2. **Batteries** — live V1, currently under benchmark validation

Planned/partially scaffolded domains:

3. Catalysis / electrocatalysis  
4. Corrosion  
5. Mechanical / creep / fatigue  
6. Additive manufacturing  
7. Photovoltaics  
8. Thermoelectrics  
9. Membranes  
10. Semiconductors  
11. Biomaterials

Do **not** assume the non-battery/non-gas domains are research-grade yet.

### Visual Intelligence V1 — COMPLETE

The shared visual layer provides native table extraction, visual provenance and sidecars, figure understanding, generated tables/charts, explicit OCR fallback, and calibrated graph digitization. It is not a canonical-admission path: OCR is explicit, and digitized points remain `estimated=true`, `origin="figure_digitized"`, with uncertainty/rejection metadata and `admission_status="not_submitted"` by default. Batteries V1 remains frozen. Read `docs/VISUAL_INTELLIGENCE_V1_STATUS.md` before changing visual code.

---

## 3. Core architectural principle

The preferred pipeline is:

```text
Research PDF
   ↓
PDF parsing
   ↓
Domain routing
   ↓
Domain-specific extractor
   ↓
Local schema validation
   ↓
Normalization / canonicalization
   ↓
Scientific semantic validation
   ↓
Provenance-aware SynthexArchive
   ↓
Search / benchmark / knowledge graph / API
```

The common platform model should support:

- sources / papers
- materials
- processes
- devices
- experiments
- calculations
- relationships
- domain payloads
- quality metrics
- evidence / provenance

Stable IDs are preferred for objects such as:

```text
src-...
mat-...
proc-...
dev-...
exp-...
calc-...
rel-...
arc-...
```

---

## 4. Current battery architecture

Battery extraction is now expected to represent the full chain:

```text
material
   ↓
synthesis
   ↓
electrode fabrication
   ↓
cell assembly
   ↓
electrochemical testing
   ↓
performance
   ↓
provenance
```

Important battery model concepts include:

- `BatteryDocument`
- `BatteryMaterial`
- `BatterySynthesis`
- synthesis process steps
- `ElectrodeFabrication`
- `CellAssembly`
- `ElectrochemicalTesting`
- `SharedBatteryProtocol`
- battery/sample groups
- `BatteryPerformancePoint`
- evidence objects
- quality / semantic warnings

The battery extractor should support papers covering:

- cathodes
- anodes
- electrolytes
- cell assembly
- electrochemical performance
- degradation / state-of-health
- EIS / impedance
- computational / DFT
- battery datasets / modeling

---

## 5. Scientific extraction rules

These rules are critical. Do not weaken them simply to make tests pass.

### Evidence and provenance

Every extracted scientific value should be traceable to the paper where possible.

Preferred evidence object:

```json
{
  "page": 3,
  "section": "2.3. Electrochemical Measurements",
  "text_snippet": "verbatim source text",
  "source_type": "text"
}
```

Evidence may sometimes arrive from the LLM as:

- a string
- one evidence object
- a list of evidence objects

The local model should safely coerce these forms without losing provenance.

### Missing information

If the paper does not report a field:

- use `null`
- use an empty list when appropriate
- do not invent explanatory pseudo-values
- do not create fake evidence like `"No value was reported."` unless that exact wording is in the paper

### Ambiguity

Do not silently “repair” source text.

Examples:

- malformed molar ratios
- apparent chemical formula typos
- inconsistent C-rates
- inconsistent cycling conditions

Preserve the reported text and add an extraction note / warning.

### Terminology

Do not conflate:

- sensor response vs sensitivity
- cyclic voltammetry (CV) vs constant-voltage charging (CV)
- reported vs inferred values
- exact numerical values vs inequalities / bounds

### Numerical qualifiers

Supported qualifiers include:

- exact
- approx
- lower_bound
- upper_bound
- range
- unknown

Preserve `raw_value` even when normalizing.

---

## 6. Gemini integration

The current extraction path uses Google Gemini through the `google-genai` package.

Environment variables:

```env
GEMINI_API_KEY=...
GEMINI_MODEL=...
```

Recommended `.env` loading behavior:

```python
load_dotenv(override=True)
```

Do not print or log API keys.

The extractor currently uses JSON-mode output and validates locally with Pydantic.

A large, deeply nested Pydantic schema should **not** be sent directly to Gemini as a response schema unless tested carefully. Earlier attempts caused `400 INVALID_ARGUMENT`. The current approach is:

1. prompt Gemini for JSON
2. parse locally
3. validate with Pydantic
4. canonicalize / normalize locally

### AFC behavior

The battery extractor is a stateless JSON request and does not use tools, so AFC is explicitly disabled in its
`Models.generate_content` configuration. A live V3.4.2 Li2FeTiO4 benchmark completed without the SDK AFC warning.
The interaction style remains a direct model request; no chat session is needed for this tool-free extraction.

### Retry behavior

The battery extractor retries transient failures such as:

- Gemini `503 UNAVAILABLE`
- `httpx.TimeoutException`
- `httpx.NetworkError`
- connection timeouts

It uses bounded exponential backoff with jitter. Local schema validation and scientific post-processing occur
outside the retry boundary and are not retried.

Do not let transient network failures corrupt scientific state or consume unrelated Serper queries.

---

## 7. Serper integration

Serper is used for **search-assisted enrichment**, not as the primary source for scientific values.

Environment variables:

```env
SERPER_API_KEY=...
SERPER_QUERY_BUDGET=2500
```

Use Serper for:

- DOI recovery
- publisher-page discovery
- supplementary-information discovery
- open-access copy discovery
- related-paper discovery
- missing bibliographic metadata

Do **not** silently populate scientific values such as:

- specific capacity
- capacity retention
- diffusion coefficient
- synthesis temperature
- electrolyte composition
- Rct

from a search snippet.

Preferred rule:

> Gemini reads. Serper finds. Synthex decides what is admissible and records where every fact came from.

### Benchmarking rule

For extraction benchmarks, Serper should be **OFF** unless the benchmark explicitly evaluates search-assisted extraction.

Otherwise benchmark scores will not measure PDF extraction fairly.

### Caching

Serper queries should be cached locally so repeated identical searches do not consume additional quota.

---

## 8. Current benchmark paper

The main battery materials benchmark currently used is:

```text
batteries-11-00142.pdf
```

Paper:

**Synthesis of Cathode Material Li2FeTiO4 for Lithium-Ion Batteries by Sol–Gel Method**

This paper was selected because it exercises a full materials-science extraction chain:

- composition
- synthesis
- multiple calcination temperatures
- electrode formulation
- doctor-blade coating
- cell assembly
- cyclic voltammetry
- galvanostatic testing
- cycling
- capacity retention
- EIS
- charge-transfer resistance
- Li-ion diffusion coefficient

Important benchmark facts include:

```text
Material: Li2FeTiO4
Method: sol-gel
Calcination variants: 600 / 700 / 800 °C

Electrode:
80 wt% active material
10 wt% acetylene black
10 wt% PVDF
NMP solvent
Al foil
doctor-blade coating
1.0 mg/cm² loading
80 °C / 12 h vacuum drying
10 MPa pressing
10 mm disks
120 °C / 6 h final vacuum drying

Cell:
CR2032
Li foil counter electrode
Celgard 2400 separator
commercial lithium electrolyte
100 µL electrolyte
Ar glovebox
O2 < 0.1 ppm
H2O < 0.1 ppm

Testing:
CV scan rate 0.1 mV/s
voltage range 1.5–4.8 V
1 C = 300 mA/g
long-term cycling around 100 cycles

700 °C sample:
first-cycle discharge specific capacity ≈ 121.3 mAh/g
100th discharge capacity ≈ 108.2 mAh/g
capacity retention ≈ 89.2%
Rct ≈ 1258.6 Ω
Li-ion diffusion coefficient ≈ 1.096 × 10^-12 cm²/s
```

Treat condition associations carefully. Some statements in the paper appear internally inconsistent, especially C-rate / cycling conditions.

Do not force a reconciliation without explicit support.

---

## 9. Known schema hardening already performed

Recent battery schema fixes include:

- compact quantity strings such as `"1.5A"` can be coerced into structured quantities
- evidence strings can be converted into evidence objects
- evidence lists are accepted where appropriate
- temperature description text is not used directly as a numerical qualifier
- synthesis step numbers may arrive as integers and are handled safely
- equipment may arrive as a string or a list
- shared protocol substructures may arrive in variant forms
- unit normalization is supported
- property-name canonicalization is supported
- protocol deduplication exists
- shared protocols can be referenced from battery groups
- battery device/sample entities are represented explicitly

Do not remove these compatibility layers unless replacing them with a demonstrably stronger implementation.

---

## 10. Shared protocol design

Repeated experimental protocols should be deduplicated.

Preferred shape:

```text
shared_protocols
   ├── protocol_A
   └── protocol_B

battery_group_1 → protocol_A
battery_group_2 → protocol_A
battery_group_3 → protocol_B
```

Do not repeat identical CC-CV / EIS / fabrication / cell-assembly data across every sample if a stable shared reference can represent it.

Deduplication should be deterministic post-processing where practical, not dependent entirely on the LLM.

---

## 11. Quality scoring

Quality scoring should not be cosmetic.

The scorer should consider:

- completeness appropriate to paper subtype
- evidence / provenance coverage
- unit-normalization coverage
- semantic warnings
- validation status

A dataset-analysis battery paper should not be penalized for lacking material synthesis.

A paper tagged `materials_synthesis` should be penalized if no synthesis/material record is extracted.

A paper tagged `electrochemical_performance` should generate a warning if no quantitative performance points are extracted.

Do not assign:

```json
{
  "completeness": 1.0,
  "provenance_coverage": 0.0,
  "unit_normalization_coverage": 0.0
}
```

unless those values are actually supported by the archive contents.

---

## 12. Current benchmark workflow

Main benchmark command:

```powershell
python benchmark_battery_material.py batteries-11-00142.pdf
```

Expected outputs are typically written under a benchmark output folder and may include:

- extracted battery document JSON
- assembled archive JSON
- benchmark report JSON

The benchmark should compare extracted facts against a manually curated gold record.

A benchmark score should not be treated as sufficient by itself. False condition associations, unsupported values, and provenance problems must also be inspected.

---

## 13. Current known issue

The most recent live benchmark failures have been in two categories:

### A. Schema-shape mismatch
Gemini returns scientifically useful data in slightly different JSON forms than Pydantic expects.

Response:
- harden local coercion
- preserve information
- do not weaken scientific constraints

### B. Network / Gemini availability
Observed failures include:

```text
503 UNAVAILABLE
httpx.ConnectTimeout
WinError 10060
```

These are external service/network failures, not battery-schema failures.

The extractor should retry them gracefully.

---

## 14. Recommended files to inspect first

Before changing anything, inspect:

```text
README.md
CURRENT_STATUS.md
ARCHITECTURE_V3.md
SERPER_INTEGRATION.md
benchmark_battery_material.py
synthex_platform/extraction/battery_extractor.py
synthex_platform/extraction/battery_models.py
synthex_platform/extraction/battery_postprocess.py
synthex_platform/
benchmark/batteries_v1/
```

Also inspect:

```text
platform_app.py
streamlit_app.py
```

to understand the UI paths.

---

## 15. First task for Codex

Do not modify anything immediately.

First:

1. Read this file.
2. Read the architecture/status docs listed above.
3. Inspect the battery extractor/model/post-processing code.
4. Run the existing test suite.
5. Report:
   - test count
   - failing tests
   - current battery extraction flow
   - current retry behavior
   - current Serper behavior
   - benchmark output paths
   - any mismatch between docs and code

Then continue only after confirming the repository state.

---

## 16. Suggested Codex prompt

Use this as the first prompt in Codex:

> Open this Synthex repository. First read `CODEX_HANDOFF.md`, `README.md`, `CURRENT_STATUS.md`, `ARCHITECTURE_V3.md`, and `SERPER_INTEGRATION.md`. Inspect the battery extraction stack, especially `benchmark_battery_material.py`, `synthex_platform/extraction/battery_extractor.py`, `battery_models.py`, and `battery_postprocess.py`. Do not modify anything yet. Run the existing tests and report the current architecture, test status, known weaknesses, and the exact path used when running the Li2FeTiO4 battery benchmark. Preserve all scientific provenance rules and do not weaken validation merely to make tests pass.

Then, after Codex reports the repository state:

> Continue debugging the `batteries-11-00142.pdf` benchmark. Fix engineering failures while preserving scientific correctness. Prefer robust coercion and deterministic canonicalization over prompt-only fixes. Do not infer unsupported scientific values. Keep Serper disabled during benchmark scoring. Run the full test suite after each code change and summarize every modification.

---

## 17. Coding principles for Synthex

Prefer:

- small domain-specific models
- explicit local validation
- deterministic normalization
- explicit provenance
- stable identifiers
- reusable archive objects
- benchmark-driven development
- test coverage for every discovered failure mode

Avoid:

- one giant unconstrained LLM prompt
- silently dropping unknown fields
- silently repairing scientific text
- using search snippets as scientific truth
- letting LLM confidence scores determine quality by themselves
- mixing paper-derived facts with web-derived enrichment
- treating a successful JSON parse as evidence of scientific correctness

---

## 18. Long-term product direction

Synthex should eventually support researcher queries such as:

```text
Find LiFePO4-like cathodes synthesized below 700 °C
with >140 mAh/g after 100 cycles at ≥1C,
compare reported diffusion barriers,
and show source evidence for every result.
```

The platform should support:

- literature-derived structured datasets
- provenance-aware experimental data
- computational descriptors
- cross-paper comparisons
- graph relationships
- benchmark datasets
- query APIs
- domain-specific validation
- machine-learning-ready exports

The goal is not to copy Materials Project, AFLOW, or NOMAD.

The differentiator is to make **experimental processing + device/testing conditions + performance + computational descriptors + provenance** queryable together.

---

## 19. Security

Never commit:

```text
.env
GEMINI_API_KEY
SERPER_API_KEY
```

Keep `.env` in `.gitignore`.

Never print secrets in logs, benchmark reports, or exception dumps.

---

## 20. Immediate roadmap

Priority order:

1. Finish Li2FeTiO4 benchmark without schema crashes.
2. Strengthen benchmark checks for condition/value association.
3. Validate against additional battery papers from the benchmark corpus.
4. Preserve completed Visual Intelligence V1 and its sidecar-only, estimated-data boundaries.
5. Improve quality scoring and provenance coverage.
6. Stress-test shared-protocol deduplication.
7. Add battery subtype-specific benchmark suites.
8. Only after Batteries V1 remains stable and this closure is reviewed, begin the next domain vertical deliberately.

Do not broaden Synthex into new domains prematurely at the cost of battery extraction quality.
