# Synthex V2.1 — Integrated Upgrade

Synthex V2.1 extends the original public Synthex project from flat nanomaterial synthesis extraction into an evidence-backed **materials → fabrication → sensor-performance** literature-mining workflow.

## What changed

- Keeps the original-style entry points: `streamlit_app.py`, `main.py`, `search.py`, `pdf_utils.py`, and `extraction/llm_extractor.py`.
- Uses Google's current `google-genai` SDK and schema-constrained structured output with `gemini-3.8-flash` by default.
- Adds nested sensor records for synthesis, deposition/fabrication, testing conditions, sensor response, sensitivity, selectivity, LOD, response time and recovery time.
- Preserves short evidence snippets and page-level provenance where PDF text extraction allows it.
- Supports **multi-PDF batch extraction** while stamping each sample with its source paper.
- Adds selectivity heat maps, response-time contour maps and normalized radar comparisons.
- Refuses to make a response-time contour from unrelated materials or from too few points.
- Preserves inequality-style measurements (for example `>400`) as raw reported values rather than silently treating them as exact numbers.
- Restores paper search through Serper using `SERPER_API_KEY`.
- Includes a real-paper **offline replay benchmark** for schema and visualization testing.

## Setup

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env` from `.env.example`:

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.8-flash
SERPER_API_KEY=your_serper_key_here
```

Do **not** commit `.env`.

## Run the web app

```bash
streamlit run streamlit_app.py
```

The app supports one or many PDFs. Multiple extracted papers are combined only after each paper has its own structured record and source provenance.

## Run the CLI

```bash
python main.py data/my_paper.pdf --category "Metal Oxides" --mode "Full Sensor Record" --format json
```

## Live Gemini smoke test

```bash
python smoke_gemini.py
```

This requires working internet access and a valid `GEMINI_API_KEY`.

## Offline real-paper replay benchmark

```bash
python benchmark/build_expected_records.py
pytest -q
```

The benchmark values are expected-value fixtures derived from published source pages. They are **not** represented as Gemini outputs.

## Visualization guardrails

### Selectivity heat map
Only exact numeric ratios or ratios calculated from explicitly extracted target/interferent responses are plotted. A reported inequality like `>400` remains available in the record but is not silently plotted as exactly 400.

### Response-time contour
A contour requires at least four response-time observations for the same **material + target analyte + sensor type**, with at least two distinct temperatures and two distinct concentrations. Otherwise Synthex shows the extracted table instead.

### Radar plot
Radar values are normalized within the selected comparison set. Interpret them only for scientifically comparable samples, especially where sensitivity definitions or units differ.

## Compatibility note

The original Synthex `LLMExtractor(category=...).extract_parameters(text)` interface is retained through an adapter in `extraction/llm_extractor.py`, but internally V2.1 generates the richer `SensorRecord` first and flattens it only for legacy callers.
