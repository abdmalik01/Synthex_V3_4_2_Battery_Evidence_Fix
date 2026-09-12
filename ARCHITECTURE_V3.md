# Synthex V3 — Materials Intelligence Platform Architecture

## Mission

Synthex V3 evolves the original PDF synthesis-parameter extractor into a FAIR-oriented materials data platform that links **literature evidence, materials, processing, experiments, calculations, properties, and benchmark datasets**.

The goal is not to imitate a single existing database. Synthex should combine:

- **Materials Project-style typed property products and API-first querying**;
- **NOMAD-style raw/processed provenance and schema-defined archives**;
- **AFLOW-style property-centric search**;
- **OPTIMADE-compatible structure exchange where appropriate**;
- a differentiator: **literature-derived experimental data and cross-domain process–structure–property–performance relationships**.

## Canonical archive

Every ingestion produces a `SynthexArchive`:

```text
Archive
├── metadata
├── sources[]             # paper/dataset/report provenance
├── materials[]           # identity, composition, phase, morphology, defects
├── processes[]           # synthesis, deposition, heat treatment, fabrication
├── experiments[]         # conditions + measured outputs
├── calculations[]        # DFT/MD/phase-field/etc. inputs + outputs
├── relationships[]       # explicit knowledge-graph edges
├── domain_payloads[]     # domain extensions
└── quality               # completeness/provenance/normalization/review
```

Stable IDs make records linkable across papers and datasets.

## Domain plugins

V3 ships manifests for:

1. gas sensing (existing mature vertical)
2. batteries
3. catalysis/electrocatalysis
4. corrosion
5. mechanical/creep/fatigue
6. additive manufacturing
7. photovoltaics
8. thermoelectrics
9. membranes
10. semiconductors
11. biomaterials

A domain manifest defines:

- preferred paper sections;
- process vocabulary;
- canonical property names and units;
- required experimental conditions;
- benchmark tasks;
- graph relation vocabulary.

This prevents the anti-pattern of maintaining one unrelated extractor per field.

## Storage model

### Stage 1 — current implementation
- append-only JSONL archive;
- graph export as `nodes.jsonl` + `edges.jsonl`;
- JSON/CSV compatibility with V2.

### Stage 2 — recommended
- raw PDFs/object storage;
- canonical JSON archive;
- Parquet/DuckDB analytical lakehouse;
- PostgreSQL for metadata/IDs/review state;
- graph layer in Neo4j/Memgraph or RDF store only when graph scale justifies it;
- vector index for semantic retrieval, separate from canonical truth data.

The vector database must not be the system of record.

## Data quality tiers

- **T0 Raw** — source file and checksum only
- **T1 Extracted** — machine extraction, schema-valid
- **T2 Normalized** — units/identifiers/ontology normalized
- **T3 Verified** — automated cross-checks and source evidence complete
- **T4 Curated** — human-reviewed benchmark-grade record

Benchmarks should publish T3/T4 subsets, not all extracted data indiscriminately.

## Benchmark strategy

Each domain must produce multiple benchmark products rather than a single dataset. Examples:

- Batteries: capacity retention, rate capability, voltage, ionic conductivity
- Catalysis: activity, product selectivity, overpotential
- Corrosion: corrosion rate, inhibitor efficiency
- Mechanical: yield strength, fatigue life, creep rupture
- Additive manufacturing: density/porosity, melt-pool geometry
- Photovoltaics: PCE, stability
- Thermoelectrics: zT, thermal conductivity
- Membranes: permeability/selectivity, rejection
- Semiconductors: band gap, mobility, defect formation energy
- Biomaterials: viability, degradation, mechanical compatibility

Every benchmark release should include a dataset card, schema version, license/provenance policy, split strategy, leakage checks, baseline model, and evaluation metric.

## Research knowledge graph

Recommended node classes:

`Material`, `Composition`, `Phase`, `Process`, `Experiment`, `Calculation`, `Property`, `Device`, `Environment`, `Source`, `Author`, `Dataset`, `Benchmark`.

Core edges:

`DERIVED_FROM`, `PROCESSED_BY`, `HAS_PHASE`, `HAS_DEFECT`, `TESTED_IN`, `CALCULATED_FOR`, `HAS_PROPERTY`, `MEASURED_UNDER`, `REPORTED_BY`, `COMPARED_WITH`.

The graph should be generated from canonical archive records, not independently extracted as an ungrounded graph.

## API strategy

V3 includes an initial FastAPI surface:

- `GET /v1/info`
- `GET /v1/domains`
- `GET /v1/domains/{slug}`
- `GET /v1/benchmarks`
- `POST /v1/archives`
- `GET /v1/archives/{archive_id}`
- `GET /v1/archives?...filters...`
- `GET /v1/optimade/structures`

Longer term, add property-specific endpoints and bulk Parquet exports.

## Extraction architecture

```text
PDF / dataset / computational output
        ↓
source parser
        ↓
domain router
        ↓
domain manifest + common extraction rules
        ↓
Gemini structured extraction
        ↓
Draft document
        ↓
ID assembler + normalization + validation
        ↓
Synthex Archive
        ├── query/index
        ├── benchmark builders
        ├── visualization
        └── knowledge graph
```

## Immediate roadmap

### V3.0 — platform foundation
- canonical archive ✓
- 11 domain manifests ✓
- stable IDs ✓
- quality scoring ✓
- local archive store ✓
- query engine ✓
- graph export ✓
- benchmark registry ✓
- API scaffold ✓
- OPTIMADE-like structure export ✓

### V3.1 — ingestion quality
- PDF multimodal/table extraction
- Visual Intelligence V1 complete: native tables, provenance sidecars, figure understanding, generated charts, explicit OCR, and calibrated graph digitization.
- DOI metadata resolution
- unit ontology and conversion library
- material/entity resolution across papers
- duplicate detection
- citation/source checksum tracking
- human review queue

### V3.2 — first expansion: batteries
- battery-specific typed schemas
- cell/electrode/electrolyte entities
- cycling curve/table extraction
- benchmark builders
- 100–500 manually verified seed papers

### V3.3 — catalysis + corrosion
- reaction-network and catalyst-site schema
- electrochemical condition normalization
- corrosion environment ontology
- benchmark releases

Visual Intelligence V1 is a shared, non-canonical sidecar layer: OCR is explicit; digitized values are estimated, retain uncertainty/rejection evidence, and are never automatically admitted to SynthexArchive.

### V3.4+ — remaining domains
Expand one domain at a time only after a verified seed benchmark exists. Avoid adding broad but low-quality schemas without curation.

## Non-negotiable design rules

1. Every numeric scientific claim keeps source evidence.
2. Raw and normalized values are both retained.
3. Conditions are part of the measurement identity.
4. Author terminology is preserved before canonicalization.
5. Derived values are labeled as derived and record their formula/input IDs.
6. Computational and experimental properties remain distinguishable but linkable.
7. Schema versions are immutable for published benchmark releases.
8. No benchmark is considered research-grade without leakage and provenance checks.
