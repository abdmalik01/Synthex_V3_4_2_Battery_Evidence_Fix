# Synthex V3 — Materials Intelligence Platform

Synthex V3 is the platform-scale evolution of Synthex. It preserves the existing gas-sensor V2 workflow and adds a cross-domain materials archive, domain registry, benchmark catalog, graph export, API scaffold, and research-quality provenance model.

## Run the V3 dashboard

```bash
pip install -r requirements.txt
streamlit run platform_app.py
```

## Run the API

```bash
uvicorn synthex_platform.api:app --reload
```

## Inspect domains and benchmarks

```bash
python platform_cli.py domains
python platform_cli.py benchmarks
```

## Build the knowledge graph

```bash
python platform_cli.py build-graph
```

## Run tests

```bash
pytest -q tests_v3 tests
```

See `ARCHITECTURE_V3.md` for the platform roadmap and design rationale.
