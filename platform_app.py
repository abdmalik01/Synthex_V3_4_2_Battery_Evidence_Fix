from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import streamlit as st

from synthex_platform.benchmarks import benchmark_matrix
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction import DomainRouter, SynthexExtractionPipeline
from synthex_platform.extraction.domain_extractor import StructuredExtractionValidationError
from synthex_platform.graph import export_graph
from synthex_platform.retrieval import DiscoveryError, discover_papers
from synthex_platform.retrieval.discovery import (
    clear_discovery_results,
    clear_saved_discovery_candidates,
    current_discovery_results,
    initialize_discovery_state,
    remove_discovery_candidate,
    save_discovery_candidate,
    saved_discovery_candidates,
    store_discovery_results,
)
from synthex_platform.storage import JsonlArchiveStore
from synthex_platform.visual.analytics import AnalyticQuery, build_visualization_spec, comparison_frame, project_archives
from synthex_platform.visual.analytics.render import VisualizationRenderer
from synthex_platform.visual.digitization import AxisCalibration, DigitizationRequest, PlotArea, SeriesSelection, digitize_plot
from synthex_platform.visual.digitization.models import PixelBoundingBox

st.set_page_config(page_title="Synthex V3.4", page_icon="🧬", layout="wide")
registry = DomainRegistry()
store = JsonlArchiveStore("data/archive/archives.jsonl")
router = DomainRouter(registry)
initialize_discovery_state(st.session_state)

st.title("Synthex V3.4 · Materials Intelligence Platform")
st.caption("Literature-derived experimental + computational materials data, with domain routing, provenance and benchmark-ready schemas.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Domain plugins", len(registry.list_domains()))
c2.metric("Archive entries", store.count())
c3.metric("Benchmark tasks", sum(len(v) for v in benchmark_matrix(registry).values()))
c4.metric("Schema", "3.4.0")

page = st.sidebar.radio("Workspace", ["Discover Papers", "Extract Paper", "Battery Validation", "Domain Registry", "Benchmark Catalog", "Visual Explorer", "Digitized Figures", "Archive Explorer", "Knowledge Graph", "Gas Sensing V2"])

if page == "Discover Papers":
    st.subheader("Discover materials-science papers")
    st.caption("Discovery results are navigation metadata only. Search snippets never become scientific evidence or canonical archive data.")

    with st.form("paper_discovery_form", border=False):
        research_query = st.text_input(
            "Research query",
            placeholder="e.g. NiFe LDH OER catalyst, ZnO NiO gas sensing, LiFePO4 cathode synthesis",
            key="synthex_discovery_query_input",
        )
        focus_label = st.selectbox(
            "Optional focus",
            ["No added focus", "Materials science", "Battery materials", "Catalysis and electrocatalysis", "Gas sensing"],
            key="synthex_discovery_focus",
        )
        number_of_results = st.number_input(
            "Results", min_value=1, max_value=10, value=5, step=1, key="synthex_discovery_num_results",
        )
        submitted = st.form_submit_button("Search papers", type="primary", icon=":material/search:")

    if submitted:
        focus = None if focus_label == "No added focus" else focus_label
        try:
            with st.spinner("Searching paper discovery index..."):
                result = discover_papers(research_query, focus=focus, num_results=int(number_of_results))
            store_discovery_results(st.session_state, result)
        except DiscoveryError as exc:
            st.error(str(exc))

    controls_left, controls_right = st.columns([1, 3])
    with controls_left:
        if st.button("Clear search results", icon=":material/clear_all:", key="synthex_clear_discovery_results"):
            clear_discovery_results(st.session_state)
    with controls_right:
        st.caption("Clearing results keeps any papers you explicitly saved for a later PDF upload.")

    result = current_discovery_results(st.session_state)
    if result:
        usage = result.usage
        cache_label = "cache hit" if result.cache_hit else "network query"
        st.caption(
            f"Query: {result.query} · {cache_label} · "
            f"local network queries: {usage.get('network_queries', 0)} · "
            f"remaining local budget: {usage.get('remaining_local_budget', 0)}"
        )
        if not result.candidates:
            st.info("No usable paper links were returned. Try a more specific materials-science query.")
        else:
            st.subheader("Discovery results")
            for candidate in result.candidates:
                with st.container(border=True):
                    st.subheader(candidate.title)
                    st.caption("Discovery result — not yet scientifically verified")
                    if candidate.snippet:
                        st.write(candidate.snippet)
                    if candidate.doi:
                        st.caption(f"DOI from direct DOI URL: {candidate.doi}")
                    st.caption(
                        f"Provider: {candidate.provider} · "
                        f"{'cache hit' if candidate.cache_hit else 'network query'} · "
                        f"recorded {candidate.retrieved_at.isoformat()}"
                    )
                    actions_left, actions_right = st.columns([1, 1])
                    with actions_left:
                        st.link_button("Open paper link", candidate.url, icon=":material/open_in_new:")
                    with actions_right:
                        already_saved = any(item.candidate_id == candidate.candidate_id for item in saved_discovery_candidates(st.session_state))
                        if st.button(
                            "Saved for extraction" if already_saved else "Save for extraction",
                            key=f"synthex_save_discovery_{candidate.candidate_id}",
                            disabled=already_saved,
                            icon=":material/bookmark_add:",
                        ):
                            save_discovery_candidate(st.session_state, candidate)
                            st.success("Saved as unverified candidate bibliography. Upload the actual PDF before extraction.")

    saved_candidates = saved_discovery_candidates(st.session_state)
    if saved_candidates:
        st.subheader("Saved for PDF upload")
        st.caption("Saved candidates are not archive records, SourceBundles, or scientific claims.")
        for candidate in saved_candidates:
            saved_left, saved_right = st.columns([4, 1])
            with saved_left:
                st.write(candidate.title)
                st.link_button("Open paper link", candidate.url, key=f"synthex_saved_link_{candidate.candidate_id}", icon=":material/open_in_new:")
            with saved_right:
                if st.button("Remove", key=f"synthex_remove_discovery_{candidate.candidate_id}", icon=":material/bookmark_remove:"):
                    remove_discovery_candidate(st.session_state, candidate.candidate_id)
        if st.button("Clear saved candidates", icon=":material/delete_sweep:"):
            clear_saved_discovery_candidates(st.session_state)

elif page == "Extract Paper":
    st.subheader("Route and extract a materials-science paper")
    st.caption("Auto Detect first classifies the scientific domain. Batteries use the V1.2 extractor with synthesis, electrode fabrication, cell assembly, shared protocols and performance records; other domains use the manifest-driven generic extractor.")

    saved_candidates = saved_discovery_candidates(st.session_state)
    if saved_candidates:
        st.info("Saved discovery candidates are optional bibliography leads only. Upload the actual PDF below; candidate metadata is not applied automatically and cannot create scientific evidence.")
        with st.expander("Saved discovery candidates"):
            for candidate in saved_candidates:
                st.write(candidate.title)
                st.link_button("Open paper link", candidate.url, key=f"synthex_extract_saved_link_{candidate.candidate_id}", icon=":material/open_in_new:")
                if candidate.doi:
                    st.caption(f"Direct DOI URL: {candidate.doi}")

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
        pipeline = SynthexExtractionPipeline(
            router=router,
            search_assisted=search_assisted,
            find_supplementary=find_supplementary,
        )
        # Build one reusable source bundle; extraction consumes this same object.
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded.getbuffer())
            tmp_path = Path(tmp.name)
        try:
            source_bundle = pipeline.build_source_bundle(tmp_path, source_filename=uploaded.name)
        finally:
            tmp_path.unlink(missing_ok=True)
        text = source_bundle.page_marked_text()

        if chosen_label == "Auto Detect":
            try:
                preview_route = router.route_text(text)
                route_name = "Generic / uncertain materials" if preview_route.domain == "generic" else registry.get(preview_route.domain)["name"]
                st.success(f"Detected domain: {route_name} · routing confidence {preview_route.confidence:.2f}")
                if preview_route.ambiguity_reason:
                    st.info(f"Safe fallback selected: {preview_route.ambiguity_reason.replace('_', ' ')}.")
                if preview_route.paper_types:
                    st.write("Detected paper types:", preview_route.paper_types)
                with st.expander("Routing evidence"):
                    st.json({"scores": preview_route.scores, "matched_terms": preview_route.matched_terms, "focal_signals": preview_route.focal_signals, "incidental_signals": preview_route.incidental_signals, "ambiguity_reason": preview_route.ambiguity_reason, "method": preview_route.method})
            except Exception as exc:
                preview_route = None
                st.warning(f"Auto-routing could not decide: {exc}. Select a domain manually.")
        else:
            st.info(f"Using selected domain: {chosen_label}")

        if st.button("Extract research record", type="primary"):
            domain = "auto" if chosen_label == "Auto Detect" else options[chosen_label]
            try:
                with st.spinner("Extracting structured scientific record with Gemini..."):
                    resolved_route, archive = pipeline.extract_source_bundle(source_bundle, domain=domain)
            except StructuredExtractionValidationError as exc:
                st.error(str(exc))
                with st.expander("Extraction validation details"):
                    st.json({
                        "route": exc.route,
                        "source_id": exc.source_id,
                        "validation_errors": exc.validation_errors,
                    })
            else:
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

elif page == "Visual Explorer":
    st.subheader("Visual Explorer")
    archives = list(store.iter_archives() or [])
    all_rows = project_archives(archives)
    properties = sorted({row.property_name for row in all_rows})
    if not properties:
        st.info("No canonical numeric archive measurements are available to visualize.")
    else:
        property_name = st.selectbox("Property", properties)
        rows = project_archives(archives, AnalyticQuery(property_name=property_name))
        frame = comparison_frame(rows)
        st.caption("Only canonical archive measurements are shown. Internal IDs and evidence references remain in downloads.")
        st.dataframe(frame, hide_index=True)
        chart_type = st.selectbox("Chart type", ["bar", "line", "scatter", "heatmap", "contour"])
        x_field = st.selectbox("X field", ["material_label", "conditions.temperature", "conditions.cycle"])
        spec = build_visualization_spec(rows, chart_type, f"{property_name} comparison", x_field=x_field, y_field="value", query=AnalyticQuery(property_name=property_name))
        if spec.eligible:
            png = VisualizationRenderer().render_png(spec, rows)
            st.image(png)
            st.download_button("Download chart PNG", png, f"{spec.visualization_id}.png", "image/png")
        else:
            st.warning(f"Chart is not eligible: {spec.reason}")
        st.download_button("Download comparison CSV", frame.to_csv(index=False).encode("utf-8"), f"{spec.visualization_id}.csv", "text/csv")
        st.download_button("Download analytic JSON", json.dumps([row.model_dump(mode="json") for row in rows], ensure_ascii=False, indent=2), f"{spec.visualization_id}.json", "application/json")

elif page == "Digitized Figures":
    st.subheader("Digitized figures")
    st.caption("Sidecar-only estimates. Confirm calibration before a dataset can be completed; no values are added to the canonical archive.")
    image_file = st.file_uploader("Rendered figure or selected panel PNG", type=["png"], key="digitization_png")
    if image_file:
        image_bytes = image_file.getvalue()
        from PIL import Image
        import io
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size
        st.image(image_bytes, caption=f"{width} × {height} px")
        with st.form("digitization_calibration"):
            source_id = st.text_input("Source ID", value="source-figure")
            figure_id = st.text_input("Figure ID", value="fig-selected")
            panel = st.text_input("Panel label (optional)") or None
            st.caption("Enter pixel bounds of the interior plot rectangle, then two visible calibration values for each axis.")
            plot_x0 = st.number_input("Plot left pixel", min_value=0.0, value=0.0)
            plot_y0 = st.number_input("Plot top pixel", min_value=0.0, value=0.0)
            plot_x1 = st.number_input("Plot right pixel", min_value=1.0, value=float(width))
            plot_y1 = st.number_input("Plot bottom pixel", min_value=1.0, value=float(height))
            x0, x1 = st.number_input("X value at left", value=0.0), st.number_input("X value at right", value=1.0)
            y0, y1 = st.number_input("Y value at bottom", value=0.0), st.number_input("Y value at top", value=1.0)
            x_log = st.checkbox("X axis is log10"); y_log = st.checkbox("Y axis is log10")
            red = st.text_input("Selected series RGB", value="228,26,28", help="A colour-selected series is required in V1.")
            submitted = st.form_submit_button("Confirm calibration and digitize", type="primary", icon=":material/analytics:")
        if submitted:
            try:
                rgb = tuple(int(value.strip()) for value in red.split(","))
                request = DigitizationRequest(source_id=source_id, page=1, figure_id=figure_id, panel=panel, plot_area=PlotArea(bbox=PixelBoundingBox(x0=plot_x0, y0=plot_y0, x1=plot_x1, y1=plot_y1), resolution_width=width, resolution_height=height), x_axis=AxisCalibration(axis="x", pixel_start=plot_x0, pixel_end=plot_x1, data_start=x0, data_end=x1, scale_type="log10" if x_log else "linear"), y_axis=AxisCalibration(axis="y", pixel_start=plot_y1, pixel_end=plot_y0, data_start=y0, data_end=y1, scale_type="log10" if y_log else "linear"), series=[SeriesSelection(series_id="series-user", color_rgb=rgb, association_status="ambiguous")])
                result = digitize_plot(image_bytes, request)
                if result.status == "completed":
                    st.success(f"Digitized {sum(len(series.points) for series in result.series)} estimated points. Label association remains {result.series[0].association_status}.")
                    st.download_button("Download digitized JSON", result.model_dump_json(indent=2), f"{result.digitization_id}.json", "application/json")
                else:
                    st.warning("Digitization was rejected: " + "; ".join(result.rejection_reasons))
            except (ValueError, TypeError) as error:
                st.error(f"Calibration was not accepted: {error}")

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
