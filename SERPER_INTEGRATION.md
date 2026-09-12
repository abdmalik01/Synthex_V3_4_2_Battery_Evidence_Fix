# Synthex V3.4 — Serper Integration

## Design principle

**Gemini reads. Serper finds. Synthex validates and records provenance.**

Serper is not allowed to populate scientific values from snippets. It may enrich missing bibliographic fields (DOI, URL, year) when a high-similarity title match is found, and it may return supplementary-information candidates for later review.

## Query budget

`SerperClient` keeps a persistent cache in `data/search_cache/` and a local request counter in `data/search_cache/stats.json`. Repeating the same query uses the cache. The default local cap is 2500 network queries and can be set with `SERPER_QUERY_BUDGET`.

## Modes

- **Paper-only extraction:** default; Gemini + local validation only. Use this for benchmarks.
- **Search-assisted extraction:** optional; after extraction, Serper is used only if bibliographic metadata is missing.
- **Supplementary discovery:** optional; adds at most one extra search for supporting/supplementary information candidates.

## Provenance

Search activity is written to a `retrieval` domain payload containing the query purpose, cache status, result candidates, title similarity, applied fields, and local usage count.
