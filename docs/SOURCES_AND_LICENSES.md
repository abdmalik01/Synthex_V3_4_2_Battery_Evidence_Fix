# Large benchmark PDF sources and redistribution review

This is a file-level review of the six PDF blobs above 10 MiB in the
unpublished development history. **None of the newly introduced third-party
PDF, workbook, or ZIP blobs is added by this metadata-only branch.** The
TE-GOLD-A supplement is publisher-linked instead of redistributed. This review is not a blanket license
for the rest of the corpus, nor legal advice. The PDFs are third-party works,
not Synthex-owned material; the repository's own license, if any, does **not**
replace their terms. Preserve the publisher's notices and credit the authors,
original publication, DOI, and [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
when redistributing a supported file. No PDF was modified for this review.
The 55 omitted local binary identities are listed in
`benchmark/omitted_binary_manifest.json` as paths, byte counts, and hashes;
that inventory does not establish redistribution rights for any file.

For all five MDPI rows below, the publisher is MDPI, the file is the
publisher-formatted open-access article PDF, the exact license is Creative
Commons Attribution 4.0 International (CC BY 4.0), and the license URL is
https://creativecommons.org/licenses/by/4.0/. The first four are research
articles; MEM-REVIEW-F is a review article. The copyright belongs to the
named authors, with the year in each row. CC BY permits redistribution,
including commercial distribution, with appropriate attribution, retention of
notices and license link, and a change indication if modified. These copies
were not modified. The sixth row is a separate Springer Nature/Nature Materials
supplement to an open-access research article, not the article PDF itself.

| Case / exact local-development file | Size / SHA-256 | Original publication and attribution | File-level finding |
| --- | --- | --- | --- |
| AM-MICRO-C — `benchmark/additive_manufacturing_v1/corpus_pdfs/materials-18-00032.pdf` | 24,994,155 bytes; `c58e6b54e7051e2742b9f584969b6744c8055c1c27f3283d6a5eb36bd216aa1b` | Zequn Feng, Haijun Pan, Wangping Wu, Zhizhi Wang, Peng Jiang, “Impact of Heat Treatment and Building Direction on Selective Laser-Melted 316L Stainless Steel: Microstructure and Mechanical Properties,” *Materials* 18, 32 (2025), [doi:10.3390/ma18010032](https://doi.org/10.3390/ma18010032). © 2024 authors. | `REDISTRIBUTION_SUPPORTED_WITH_ATTRIBUTION`: this exact PDF's first page states CC BY 4.0. |
| AM-MECH-D — `benchmark/additive_manufacturing_v1/corpus_pdfs/metals-11-00619.pdf` | 12,691,837 bytes; `ded2c3bfd4f028004d799bb6eea7d0e89a53bdfa90ba9de3d6af54e4e30e4be3` | Thibaut De Terris, Olivier Castelnau, Zehoua Hadjem-Hamouche, Halim Haddadi, Vincent Michel, Patrice Peyre, “Analysis of As-Built Microstructures and Recrystallization Phenomena on Inconel 625 Alloy Obtained via Laser Powder Bed Fusion (L-PBF),” *Metals* 11, 619 (2021), [doi:10.3390/met11040619](https://doi.org/10.3390/met11040619). © 2021 authors. | `REDISTRIBUTION_SUPPORTED_WITH_ATTRIBUTION`: this exact PDF's first page states CC BY 4.0. |
| MECH-FRACTURE-E — `benchmark/mechanical_v1/corpus_pdfs/materials-14-05875.pdf` | 11,745,877 bytes; `1166ad7b5831aae12f58e551882cabbfc6b4fc7d08a9ed8a6a9a92a0788b1614` | Jaroslav Pokluda, Ivo Dlouhý, Marta Kianicová, Jan Čupera, Jana Horníková, Pavel Šandera, “Temperature Dependence of Fracture Characteristics of Variously Heat-Treated Grades of Ultra-High-Strength Steel: Experimental and Modelling,” *Materials* 14, 5875 (2021), [doi:10.3390/ma14195875](https://doi.org/10.3390/ma14195875). © 2021 authors. | `REDISTRIBUTION_SUPPORTED_WITH_ATTRIBUTION`: this exact PDF's first page states CC BY 4.0. |
| MECH-HARD-D — `benchmark/mechanical_v1/corpus_pdfs/metals-11-01014.pdf` | 15,649,335 bytes; `a6b8238d176150f22b1daf25bf347202ad87d795074835b46db29d287074783a` | Velaphi Jeffrey Matjeke, Josias Willem van der Merwe, Nontuthuzelo Lindokuhle Vithi, “Determination of Critical Transformation Temperatures for the Optimisation of Spring Steel Heat Treatment Processes,” *Metals* 11, 1014 (2021), [doi:10.3390/met11071014](https://doi.org/10.3390/met11071014). © 2021 authors. | `REDISTRIBUTION_SUPPORTED_WITH_ATTRIBUTION`: this exact PDF's first page states CC BY 4.0. |
| MEM-REVIEW-F — `benchmark/membranes_v1/corpus_pdfs/mem_review_f_polymeric_aging_review.pdf` | 10,987,218 bytes; `82433ab21253a63b1ad77a02ff38fd0c2f722d75dd461f202ce0f6712f14adb1` | Farahdila Kadirkhan, Pei Sean Goh, Ahmad Fauzi Ismail, Wan Nurul Ffazida Wan Mustapa, Mohd Hanif Mohamad Halim, Wei Kian Soh, Siew Yean Yeo, “Recent Advances of Polymeric Membranes in Tackling Plasticization and Aging for Practical Industrial CO2/CH4 Applications—A Review,” *Membranes* 12, 71 (2022), [doi:10.3390/membranes12010071](https://doi.org/10.3390/membranes12010071). © 2022 authors. | `REDISTRIBUTION_SUPPORTED_WITH_ATTRIBUTION`: this exact PDF's first page states CC BY 4.0. |
| TE-GOLD-A supplementary — `benchmark/thermoelectrics_v1/corpus_pdfs/TE-GOLD-A_supplementary.pdf` | 10,565,160 bytes; `7f3f950c6e2385622056cfd49481edca38cd0e40234f2dc3ef84dc112a9d05de` | Chongjian Zhou, Yong Kyu Lee, Yuan Yu *et al.*, “Polycrystalline SnSe with a thermoelectric figure of merit greater than the single crystal,” *Nature Materials* 20, 1378–1384 (2021), [doi:10.1038/s41563-021-01064-6](https://doi.org/10.1038/s41563-021-01064-6). The [publisher's supplementary PDF](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41563-021-01064-6/MediaObjects/41563_2021_1064_MOESM1_ESM.pdf) is the source. | `HUMAN_LEGAL_REVIEW_REQUIRED`: the separate 46-page supplement contains no explicit CC/copyright/license notice found by whole-document text inspection. The article page licenses **the article** CC BY 4.0 and links the supplement, but does not explicitly state that this separate PDF has the same redistribution grant. Do not infer the supplement's rights from the article's license or from free download access. |

MDPI's [rights policy](https://www.mdpi.com/authors/rights) and
[open-access policy](https://www.mdpi.com/openaccess) support reuse with source
credit; the five MDPI *files themselves* also contain the CC BY notice. The
[Nature Materials article page](https://www.nature.com/articles/s41563-021-01064-6)
lists the separate supplement and the article's rights statement. It does not
resolve the supplement's license scope. The [CC BY 4.0 terms](https://creativecommons.org/licenses/by/4.0/legalcode)
require retained notices, appropriate credit, a license link, and a change
indication when applicable; the reviewed local development copies were unchanged.
The five local MDPI first pages identify their publishers, titles, DOIs,
copyright holders, and CC BY notices. The local Nature supplement cover
identifies the article DOI and publisher format. A current hosted-file
SHA-256 comparison was not available, so this is an identification of the
locally held publisher-formatted copies, not a claim of remote byte-for-byte
identity.

**Release path: `METADATA_ONLY`.** All newly introduced corpus binaries are
absent from this branch and its new commits. Source locks retain their exact
SHA-256 values; publisher links provide independent retrieval where known.
The `license: CC BY 4.0` value in the historical TE-GOLD-A source lock should
be read as article metadata, **not** a redistribution grant for the separate
supplement. The article's CC BY notice is not treated as permission to
redistribute that supplement. The preserved local-only
`unpublished-corpus-history` branch still contains its PDF and must **not** be
pushed as-is. Public retrieval is not itself a redistribution license.
