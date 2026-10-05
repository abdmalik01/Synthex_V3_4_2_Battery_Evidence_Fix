# Membranes V1 frozen architecture

Status: scientifically closed after eight offline cases, 40 invariants, and the preserved historical live gate.

Lineage is `materials -> fabrication process -> membrane specimen -> separation experiment`.
Every experimental record belongs to exactly one membrane specimen. Multilayer specimens retain
ordered `substrate/support -> interlayer -> selective layer -> protective layer` roles. Dense and
mixed-matrix films use a `membrane_body` role rather than pretending their constituents are layers.

The scientific contract keeps permeability, permeance, flux, selectivity, separation factor,
rejection, retention, and fouling/recovery metrics distinct. Gas permeability admits Barrer but not
GPU; gas permeance admits GPU or explicit permeance dimensions but not Barrer. No permeability to
permeance conversion occurs without an explicit derived-value record and thickness basis.

Computational membrane transport uses CalculationRecord exclusively. Its calculated permeability
coefficient and apparent diffusion coefficient have distinct property keys, scientific types, and
units from experimental gas permeability and permeance. Explicit reviews require both a publisher
Review label and author self-description before whole-document non-focal containment activates.

## Eight-case corpus

1. `MEM-GOLD-A`: mixed-gas CO2/CH4 permeability and selectivity for four CTF/Matrimid variants.
2. `MEM-SEP-B`: six pure gases and eight ideal-selectivity pairs for seven dense MMM variants.
3. `MEM-STAB-C`: initial, fouled and recovered flux plus author-reported FRR/RFR for five variants.
4. `MEM-PROCESS-D`: ordered four-layer TFC architectures and species-specific transport results.
5. `MEM-COMPUTE-E`: NAMD2/CHARMM36 lipid-bilayer gas transport, segregated as CalculationRecord.
6. `MEM-REVIEW-F`: dual-signal review detection and cited-value ownership containment.
7. `MEM-NEG-G`: lithium-ion battery separator routing control.
8. `MEM-MIXED-H`: supported TiO2 architecture, suspension plasma spray, filtration fouling, and self-cleaning.

The corpus contains 215 canonical outputs: 183 experimental and 32 computational. Review and
negative controls contribute zero canonical outputs. Raw provider extraction remains model-specific
and does not become canonical solely because append-only normalization makes its shape schema-valid.
