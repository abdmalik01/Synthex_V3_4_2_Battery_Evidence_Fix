# Research UI V1 and LLM Provider Resilience V1

Status: **COMPLETE**

## Research UI boundary

The primary Streamlit workspace leads with Home, Analyze Paper, Discover Papers, Explore Results,
and Visualize Data. Advanced navigation retains figure digitization, validation and benchmark
catalogs, provider diagnostics, domain registry, graph export, and the legacy gas-sensing entry
point. No prior workflow was removed.

Paper summaries, result highlights, filters, trust labels, and downloads are derived from the
validated `SynthexArchive`. `Verified`, `Admitted`, `Estimated`, and `Needs review` are display
translations only. Exact evidence origin/strength, ownership, admission status, estimated state,
source/page, uncertainty, and quarantine reason remain visible. UI exploration performs no PDF
parsing, LLM call, Serper call, web lookup, or canonical mutation.

## Provider boundary

Production requests resolve the preferred `GEMINI_MODEL`, then the ordered comma-separated
`GEMINI_FALLBACK_MODELS`. Duplicate names are removed without changing order. Each model receives
at most one primary attempt. Failover is limited to provider/model unavailability, timeout, and
transport failure. Authentication, quota, safety, unexpected application errors, structured-output
validation, and scientific validation stop immediately.

Benchmark scripts pass `provider_mode="benchmark"` and use one explicit model. A bounded schema
repair remains pinned to the model that produced the primary response. The audit payload records
mode, requested and actual models, configured and attempted order, fallback status, phases,
timestamps, and redacted provider failure summaries. It never records API keys.

The Advanced provider diagnostic is opt-in. It sends one tiny request per configured model and
does not claim that a successful probe guarantees full extraction readiness.

## Configuration

```env
GEMINI_MODEL=gemini-3.8-flash
GEMINI_FALLBACK_MODELS=gemini-3.5-flash,gemini-3.6-flash,gemini-3.7-flash
```

Omitting `GEMINI_FALLBACK_MODELS` preserves compatibility by using the approved built-in model
set after the preferred model. Existing `GEMINI_MODEL` configuration remains valid.
