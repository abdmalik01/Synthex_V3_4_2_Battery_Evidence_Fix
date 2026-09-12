from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import streamlit as st

from synthex_platform.benchmarks import benchmark_matrix
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction import DomainRouter, SynthexExtractionPipeline
from synthex_platform.graph import export_graph
from synthex_platform.storage import JsonlArchiveStore
from synthex_v2.pdf_utils_v2 import extract_pages, pages_to_marked_text

st.set_page_config(page_title="Synthex V3.4", page_icon="🧬", layout="wide")
registry = DomainRegistry()
store = JsonlArchiveStore("data/archive/archives.jsonl")
router = DomainRouter(registry)

st.title("Synthex V3.4 · Materials Intelligence Platform")
st.caption("Literature-derived experimental + computational materials data, with domain routing, provenance and benchmark-ready schemas.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Domain plugins", len(registry.list_domains()))
c2.metric("Archive entries", store.count())
c3.metric("Benchmark tasks", sum(len(v) for v in benchmark_matrix(registry).values()))
c4.metric("Schema", "3.4.0")

page = st.sidebar.radio("Workspace", ["Extract Paper", "Battery Validation", "Domain Registry", "Benchmark Catalog", "Archive Explorer", "Knowledge Graph", "Gas Sensing V2"])

if page == "Extract Paper":
    st.subheader("Route and extract a materials-science paper")
    st.caption("Auto Detect first classifies the scientific domain. Batteries use the V1.2 extractor with synthesis, electrode fabrication, cell assembly, shared protocols and performance records; other domains use the manifest-driven generic extractor.")

    options = {d["name"]: d["slug"] for d in registry.list_domains()}
    domain_labels = ["Auto Detect"] + list(options)
    chosen_label = st.selectbox("Domain", domain_labels, index=0)
    search_assisted = st.checkbox(
        "Search-assisted enrichment with Serper",
        value=False,
        help="Uses Serper only for missing bibliographic metadata and discovery. Search snippets never populate scientific measurements.",
    )
    find_supplementary = False
    if search_assisted:
        if os.getenv("SERPER_API_KEY"):
            st.caption("Serper configured. Cached searches do not consume another query.")
            find_supplementary = st.checkbox(
                "Also search for supplementary/supporting information",
                value=False,
                help="Adds at most one additional cached search for supplementary-information candidates. It does not automatically ingest those files.",
            )
        else:
            st.warning("SERPER_API_KEY is not configured in .env. Search-assisted mode will fail until you add it.")
    uploaded = st.file_uploader("Upload PDF", type=["pdf"])

    if uploaded:
        # Parse the current upload on every rerun; keep the much larger extracted archive in session state.
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded.getbuffer())
            tmp_path = Path(tmp.name)
        try:
            pages = extract_pages(str(tmp_path))
            text = pages_to_marked_text(pages)
        finally:
            tmp_path.unlink(missing_ok=True)

        if chosen_label == "Auto Detect":
            try:
                preview_route = router.route_text(text)
                st.success(f"Detected domain: {registry.get(preview_route.domain)['name']} · routing confidence {preview_route.confidence:.2f}")
                if preview_route.paper_types:
                    st.write("Detected paper types:", preview_route.paper_types)
                with st.expander("Routing evidence"):
                    st.json({"scores": preview_route.scores, "matched_terms": preview_route.matched_terms, "method": preview_route.method})
            except Exception as exc:
                preview_route = None
                st.warning(f"Auto-routing could not decide: {exc}. Select a domain manually.")
        else:
            st.info(f"Using selected domain: {chosen_label}")

        if st.button("Extract research record", type="primary"):
            domain = "auto" if chosen_label == "Auto Detect" else options[chosen_label]
            with st.spinner("Extracting structured scientific record with Gemini..."):
                pipeline = SynthexExtractionPipeline(
                    router=router,
                    search_assisted=search_assisted,
                    find_supplementary=find_supplementary,
                )
                resolved_route, archive = pipeline.extract_text(text, domain=domain)
            st.session_state["synthex_last_archive"] = archive.model_dump(exclude_none=True)
            st.session_state["synthex_last_route"] = resolved_route.domain

    archive_data = st.session_state.get("synthex_last_archive")
    if archive_data:
        st.success(f"Latest extraction complete · {st.session_state.get('synthex_last_route', 'unknown')}")
        st.json(archive_data)
        col1, col2 = st.columns(2)
        with col1:
            archive_id = archive_data.get("metadata", {}).get("archive_id", "synthex_record")
            st.download_button(
                "Download archive JSON",
                data=json.dumps(archive_data, ensure_ascii=False, indent=2),
                file_name=f"{archive_id}.json",
                mime="application/json",
            )
        with col2:
            if st.button("Save latest extraction to local Synthex Archive"):
                from synthex_platform.core.archive import SynthexArchive
                store.append(SynthexArchive.model_validate(archive_data))
                st.success("Saved to data/archive/archives.jsonl")


elif page == "Battery Validation":
    st.subheader("Batteries V1.2 validation corpus")
    st.info("Benchmark runs are paper-only by design: Serper enrichment is OFF during scoring so retrieval cannot leak answers into extraction benchmarks.")
    manifest_path = Path("benchmark/batteries_v1/corpus_manifest.json")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        a,b,c,d = st.columns(4)
        a.metric("Files", manifest.get("total_files", 0))
        b.metric("Unique", manifest.get("unique_files", 0))
        c.metric("Battery-relevant", manifest.get("battery_relevant_unique", 0))
        d.metric("Negative controls", manifest.get("negative_controls", 0))
        rows = [x for x in manifest.get("entries", []) if x.get("benchmark_priority") != "EXCLUDE"]
        st.dataframe(rows, use_container_width=True)
    st.markdown("**Primary gold benchmark:** `batteries-11-00142.pdf` (Li2FeTiO4 sol–gel cathode).")
    st.code('python benchmark_battery_material.py "path/to/batteries-11-00142.pdf"', language="powershell")
    st.caption("The live runner saves the extracted document, assembled archive and field-level benchmark report under benchmark/outputs/.")

elif page == "Domain Registry":
    st.subheader("Scientific domain registry")
    options = {d["name"]: d["slug"] for d in registry.list_domains()}
    chosen = st.selectbox("Domain", list(options))
    spec = registry.get(options[chosen])
    st.write(spec["description"])
    maturity = {
        "gas_sensing": "Mature V2 vertical: live extraction + validation + visualizations",
        "batteries": "Live V1.2 vertical: routing + synthesis + electrode/cell protocols + performance + benchmark corpus",
    }.get(options[chosen], "Platform scaffold: ontology + manifest + generic extractor; not yet benchmark-validated")
    st.info(maturity)
    left, right = st.columns([1, 2])
    with left:
        st.markdown("**Process vocabulary**")
        st.write(spec.get("process_vocabulary", []))
        st.markdown("**Recommended paper sections**")
        st.write(spec.get("recommended_sections", []))
    with right:
        st.markdown("**Canonical properties**")
        st.dataframe(spec.get("properties", []), use_container_width=True)
    with st.expander("Raw domain manifest"):
        st.json(spec)

elif page == "Benchmark Catalog":
    st.subheader("Benchmark dataset roadmap")
    matrix = benchmark_matrix(registry)
    for domain, tasks in matrix.items():
        with st.expander(f"{registry.get(domain)['name']} · {len(tasks)} tasks"):
            for task in tasks:
                st.write("•", task)

elif page == "Archive Explorer":
    st.subheader("Local Synthex Archive")
    archives = list(store.iter_archives() or [])
    st.write(f"{len(archives)} archived entries")
    if archives:
        domains = ["All"] + sorted({a.metadata.domain for a in archives if a.metadata.domain})
        d = st.selectbox("Filter domain", domains)
        shown = [a for a in archives if d == "All" or a.metadata.domain == d]
        for a in shown:
            title = a.sources[0].title if a.sources else a.metadata.archive_id
            with st.expander(f"{title or 'Untitled'} · {a.metadata.domain}"):
                st.json(a.model_dump(exclude_none=True))
    else:
        st.info("No archives yet. V3 uses data/archive/archives.jsonl as its local append-only archive.")

elif page == "Knowledge Graph":
    st.subheader("Knowledge graph export")
    archives = list(store.iter_archives() or [])
    if st.button("Build nodes.jsonl + edges.jsonl"):
        nodes, edges = export_graph(archives, "data/graph")
        st.success(f"Built {nodes} and {edges}")
    st.markdown("Graph relations include `processed_by`, `tested_in`, `calculated_for`, `has_property`, and `reported_by`.")

else:
    st.subheader("Gas Sensing V2")
    st.info("The existing Synthex V2 gas-sensing application remains available through `streamlit run streamlit_app.py`. V3 treats it as the first mature domain plugin rather than deleting it.")
