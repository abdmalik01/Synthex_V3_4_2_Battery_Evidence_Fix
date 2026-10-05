# Thermoelectrics V1

Thermoelectrics V1 treats a transport value as canonical only when the material, property identity,
temperature, orientation, scientific type, unit, and value-specific primary-source evidence are all
explicit. Seebeck values retain their sign. Total, lattice, and electronic thermal conductivity remain
distinct properties. Reported measurements remain distinct from author-derived power factor, thermal
conductivity components, and zT.

## TE-GOLD-A

TE-GOLD-A is the open-access primary study “Polycrystalline SnSe with a thermoelectric figure of merit
greater than the single crystal” (Nature Materials 20, 1378–1384, 2021;
doi:10.1038/s41563-021-01064-6). The link-only corpus contains the publisher article PDF
and source-data workbooks for Figs. 4 and 5. The supplementary PDF remains locked by URL,
SHA-256, and page count, but its bytes are not redistributed. A user may download the
[publisher's supplement](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41563-021-01064-6/MediaObjects/41563_2021_1064_MOESM1_ESM.pdf)
to `corpus_pdfs/TE-GOLD-A_supplementary.pdf` for local verification. Its locked SHA-256 is
`7f3f950c6e2385622056cfd49481edca38cd0e40234f2dc3ef84dc112a9d05de` (46 pages).
An absent copy is `not_available_locally`; a present copy with a wrong hash or page count fails.

The focal material is purified polycrystalline Na0.03Sn0.965Se measured parallel to the spark-plasma-
sintering direction. The deterministic recovery reads exact workbook cells for electrical conductivity,
signed Seebeck coefficient, power factor, zT, lattice thermal conductivity, and total thermal
conductivity. It creates one material-linked experimental series per property and retains whether each
series is measured or author-derived.

The frozen gold stores source checksums, complete-series digests, counts, and sentinel points. It was
defined before any provider run. Provider output may be scored against it but cannot alter it or bypass
the scientific admission contract. Offline recovery without the supplement replays exact publisher
workbook values and a previously locked Supplementary Table 1 excerpt for 95.6% relative density;
it does **not** reverify that excerpt against missing PDF bytes. The frozen gold is unchanged.

## Eight-case corpus plan

- **TE-GOLD-A** — locked primary-source temperature-dependent transport data and processing.
- **TE-SERIES-B** — dense Seebeck, electrical-conductivity, and thermal-conductivity series.
- **TE-DERIVED-C** — source-reported power-factor and zT derivation semantics.
- **TE-ANISO-D** — directional measurements that test orientation and anisotropy retention.
- **TE-COMPUTE-E** — DFT, Boltzmann-transport, or phonon calculations kept separate from experiment.
- **TE-REVIEW-F** — review/citation ownership containment with no borrowed values admitted as focal work.
- **TE-NEG-G** — non-thermoelectric negative control using incidental transport terminology.
- **TE-MIXED-H** — mixed experimental/computational and multi-property association stress case.

V1 admits experimental outputs into ExperimentRecord objects and explicitly calculated outputs into
CalculationRecord objects. A computational output must carry scientific_type=calculated and cannot be
admitted through an experiment. TE-GOLD-A covers one
focal p-type polycrystalline composition and one measurement orientation; it does not yet validate
multi-sample association, n-type carriers, tensor components, plot digitization, uncertainty propagation,
or device/module hot-side and cold-side operating conditions.

## V1 freeze

The eight-case deterministic closure contains 428 exact canonical outputs: 396 experimental or
author-reported-derived outputs and 32 computational outputs. All 40 scientific invariants pass with
zero ownership, evidence, cross-record, or analytics contamination. Review values remain
noncanonical, and the photovoltaic negative control creates no Thermoelectrics records.

The live gate is satisfied by an auditable Gemini payload for TE-GOLD-A. That payload is
scientifically scored but schema-invalid and not canonically admitted; provider quality is therefore
model-specific and does not weaken deterministic admission. Gemini is the active live provider.
OpenAI remains `FUTURE_SUPPORTED_BUT_INACTIVE` behind the provider-neutral boundary.
