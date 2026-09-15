from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import streamlit as st

from synthex_platform.benchmarks import benchmark_matrix
from synthex_platform.core.archive import SynthexArchive
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.explorer import (
    ExplorerFilters,
    archive_summary,
    build_archive_explorer,
    filter_options,
    filter_results,
    result_highlights,
)
from synthex_platform.export import export_csv_bundle_zip, export_results_csv, export_results_rows_csv
from synthex_platform.extraction import DomainRouter, SynthexExtractionPipeline
from synthex_platform.extraction.catalysis_extractor import CatalysisStructuredExtractionValidationError
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
from synthex_platform.providers import (
    GeminiModelsUnavailableError,
    configured_gemini_models,
    probe_configured_gemini,
)
from synthex_platform.ui_empty_state import archive_empty_state
from synthex_platform.visual.analytics import AnalyticQuery, build_visualization_spec, comparison_frame, project_archives
from synthex_platform.visual.analytics.render import VisualizationRenderer
from synthex_platform.visual.digitization import AxisCalibration, DigitizationRequest, PlotArea, SeriesSelection, digitize_plot
from synthex_platform.visual.digitization.models import PixelBoundingBox

st.set_page_config(page_title="Synthex · Materials Intelligence", page_icon="🧬", layout="wide")
registry = DomainRegistry()
store = JsonlArchiveStore("data/archive/archives.jsonl")
router = DomainRouter(registry)
initialize_discovery_state(st.session_state)


@st.cache_data(max_entries=8, show_spinner=False)
def _cached_archive_explorer(archive_json: str, include_quarantined: bool):
    """Cache the derived view only; the validated archive remains authoritative."""
    return build_archive_explorer(
        SynthexArchive.model_validate_json(archive_json),
        include_quarantined=include_quarantined,
    )


def _navigate(destination: str) -> None:
    st.session_state["synthex_workspace"] = destination


def _render_archive_summary(archive: SynthexArchive) -> None:
    summary = archive_summary(archive)
    st.subheader(summary["title"])
    source_bits = [f"Domain: {summary['domain']}"]
    if summary["doi"]:
        source_bits.append(f"DOI: {summary['doi']}")
    if summary["source_id"]:
        source_bits.append(f"Source: {summary['source_id']}")
    st.caption(" · ".join(source_bits))
    columns = st.columns(5)
    columns[0].metric("Materials", summary["materials"])
    columns[1].metric("Experiments", summary["experiments"])
    columns[2].metric("Calculations", summary["calculations"])
    columns[3].metric("Admitted results", summary["admitted_observations"])
    columns[4].metric("Needs review", summary["quarantined_observations"])


def _render_empty_results_state(archive: SynthexArchive, *, result_count: int) -> bool:
    """Explain why an extraction can validly contain no researcher-facing result rows."""
    state = archive_empty_state(archive, result_count=result_count)
    if state is None:
        return False
    with st.container(border=True):
        st.subheader(state["title"])
        st.write(state["message"])
        if state.get("kind") == "review_no_focal_data":
            st.caption(
                "This is an intentional scientific-safety outcome, not an extraction failure: "
                "reviewed/cited literature is not relabelled as the focal paper's own dataset."
            )
        elif state.get("kind") == "quarantined_only":
            st.caption(f"Quarantined candidates available for review: {state.get('quarantined', 0)}")
        details = state.get("details") or []
        if details:
            with st.expander("Why Synthex made this decision"):
                for note in details:
                    st.write(f"• {note}")
    return True


NAVIGATION = (
    "Home",
    "Analyze Paper",
    "Discover Papers",
    "Explore Results",
    "Visualize Data",
    "Advanced · Figure Data",
    "Advanced · Battery validation",
    "Advanced · Benchmark catalog",
    "Advanced · Diagnostics",
    "Advanced · Domain registry",
    "Advanced · Knowledge graph",
    "Advanced · Gas sensing V2",
)
st.sidebar.title("SYNTHEX")
st.sidebar.caption("Materials intelligence workspace")
page = st.sidebar.radio("Workspace", NAVIGATION, key="synthex_workspace")

if page == "Home":
    st.title("SYNTHEX")
    st.subheader("Materials Intelligence from Scientific Literature")
    st.write(
        "Turn scientific papers into evidence-linked materials data that can be reviewed, "
        "explored, visualized, and exported."
    )
    with st.container(horizontal=True):
        st.button("Analyze a paper", type="primary", icon=":material/upload_file:", on_click=_navigate, args=("Analyze Paper",))
        st.button("Discover papers", icon=":material/search:", on_click=_navigate, args=("Discover Papers",))
    st.subheader("What Synthex can do")
    capabilities = st.columns(3)
    with capabilities[0]:
        with st.container(border=True):
            st.write("Extract structured science")
            st.caption("Route uploaded PDFs and preserve scientific fields under strict schemas.")
    with capabilities[1]:
        with st.container(border=True):
            st.write("Keep evidence visible")
            st.caption("Track source, page, origin, ownership, admission, uncertainty, and quarantine.")
    with capabilities[2]:
        with st.container(border=True):
            st.write("Explore and export")
            st.caption("Review researcher-friendly results while retaining exact machine fields and CSV/JSON exports.")
    st.subheader("Workspace status")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Domain plugins", len(registry.list_domains()))
    c2.metric("Saved archives", store.count())
    c3.metric("Benchmark tasks", sum(len(v) for v in benchmark_matrix(registry).values()))
    c4.metric("Archive schema", "3.4.0")
    st.info(
        "Batteries V1.3 and Visual Intelligence V1 are frozen. Catalysis/Electrocatalysis V1 "
        "Stages 1–3 are closed; Stage 4 hardening/freeze is ready but has not begun."
    )

elif page == "Discover Papers":
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

elif page == "Analyze Paper":
    st.subheader("Analyze a scientific paper")
    st.caption("Upload → analyze → review → explore → export")
    st.caption("Auto Detect first classifies the scientific domain. Batteries use the V1.3 extractor with synthesis, electrode fabrication, cell assembly, shared protocols and performance records; other domains use the manifest-driven generic extractor.")

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
            except (StructuredExtractionValidationError, CatalysisStructuredExtractionValidationError) as exc:
                st.error(str(exc))
                with st.expander("Extraction validation details"):
                    details = {
                        "route": exc.route,
                        "source_id": exc.source_id,
                        "validation_errors": exc.validation_errors,
                    }
                    if isinstance(exc, CatalysisStructuredExtractionValidationError):
                        details.update({
                            "repair_attempted": exc.repair_attempted,
                            "raw_output_reference": exc.raw_output_reference,
                        })
                    st.json(details)
            except GeminiModelsUnavailableError as exc:
                st.error(
                    "The configured Gemini models are temporarily unavailable. "
                    "No scientific record was created; try again later or review Advanced · Diagnostics."
                )
                with st.expander("Provider attempt details"):
                    st.json(exc.audit)
            else:
                st.session_state["synthex_last_archive"] = archive.model_dump(exclude_none=True)
                st.session_state["synthex_last_route"] = resolved_route.domain

    archive_data = st.session_state.get("synthex_last_archive")
    if archive_data:
        st.success(f"Latest extraction complete · {st.session_state.get('synthex_last_route', 'unknown')}")
        archive = SynthexArchive.model_validate(archive_data)
        _render_archive_summary(archive)
        explorer = _cached_archive_explorer(archive.model_dump_json(exclude_none=True), False)
        highlights = result_highlights(explorer.results)
        if highlights:
            st.write("Result highlights")
            for highlight in highlights:
                label = highlight.get("metric") or highlight.get("experiment_type") or "Scientific observation"
                value = " ".join(str(item) for item in (highlight.get("value"), highlight.get("unit")) if item not in (None, ""))
                with st.container(border=True):
                    st.write(f"{label}: {value or 'Recorded'}")
                    st.caption(
                        f"{highlight['researcher_status']} · page {highlight.get('source_page') or 'not resolved'} · "
                        f"evidence {highlight.get('evidence_origin') or 'not recorded'}"
                    )
        else:
            _render_empty_results_state(archive, result_count=len(explorer.results))
        st.button("Explore all results", type="primary", on_click=_navigate, args=("Explore Results",))
        with st.expander("Complete validated archive"):
            st.json(archive_data)
        archive_id = archive.metadata.archive_id or "synthex_record"
        st.subheader("Export Results")
        include_quarantined = st.checkbox(
            "Include quarantined records in CSV exports",
            value=False,
            help=(
                "Off exports canonical/admitted records only. When enabled, quarantined records "
                "are included with explicit admission status, ownership, reason, and audit path."
            ),
            key="synthex_export_include_quarantined",
        )
        results_name = "results_all.csv" if include_quarantined else "results.csv"
        with st.container(horizontal=True):
            st.download_button(
                "Download JSON",
                data=json.dumps(archive_data, ensure_ascii=False, indent=2),
                file_name=f"{archive_id}.json",
                mime="application/json",
                on_click="ignore",
                icon=":material/download:",
            )
            st.download_button(
                "Download CSV",
                data=export_results_csv(archive, include_quarantined=include_quarantined),
                file_name=results_name,
                mime="text/csv",
                on_click="ignore",
                icon=":material/table_view:",
            )
            st.download_button(
                "Download CSV Bundle",
                data=export_csv_bundle_zip(archive, include_quarantined=include_quarantined),
                file_name=f"{archive_id}_csv_bundle.zip",
                mime="application/zip",
                on_click="ignore",
                icon=":material/folder_zip:",
            )
            if st.button("Save latest extraction to local Synthex Archive"):
                store.append(archive)
                st.success("Saved to data/archive/archives.jsonl")


elif page == "Advanced · Battery validation":
    st.subheader("Batteries V1.3 validation corpus")
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
        st.dataframe(rows, width="stretch")
    st.markdown("**Primary gold benchmark:** `batteries-11-00142.pdf` (Li2FeTiO4 sol–gel cathode).")
    st.code('python benchmark_battery_material.py "path/to/batteries-11-00142.pdf"', language="powershell")
    st.caption("The live runner saves the extracted document, assembled archive and field-level benchmark report under benchmark/outputs/.")

elif page == "Advanced · Domain registry":
    st.subheader("Scientific domain registry")
    options = {d["name"]: d["slug"] for d in registry.list_domains()}
    chosen = st.selectbox("Domain", list(options))
    spec = registry.get(options[chosen])
    st.write(spec["description"])
    maturity = {
        "gas_sensing": "Mature V2 vertical: live extraction + validation + visualizations",
        "batteries": "Frozen V1.3 vertical: routing + synthesis + electrode/cell protocols + performance + benchmark corpus",
        "catalysis": "Stage 3 closed: heterogeneous catalysis, electrocatalysis, computational DFT, stability and review-ownership safeguards; Stage 4 freeze pending",
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
        st.dataframe(spec.get("properties", []), width="stretch")
    with st.expander("Raw domain manifest"):
        st.json(spec)

elif page == "Advanced · Benchmark catalog":
    st.subheader("Benchmark dataset roadmap")
    matrix = benchmark_matrix(registry)
    for domain, tasks in matrix.items():
        with st.expander(f"{registry.get(domain)['name']} · {len(tasks)} tasks"):
            for task in tasks:
                st.write("•", task)

elif page == "Visualize Data":
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

elif page == "Advanced · Figure Data":
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

elif page == "Explore Results":
    st.subheader("Explore Results")
    st.caption(
        "Browse and filter the structured information Synthex extracted from the current paper. "
        "All views are local and read-only."
    )
    archive_data = st.session_state.get("synthex_last_archive")
    if not archive_data:
        st.info("No current extraction to explore. Extract a paper first, then return here.")
    else:
        current_archive = SynthexArchive.model_validate(archive_data)
        _render_archive_summary(current_archive)
        source = current_archive.sources[0] if current_archive.sources else None
        with st.container(border=True):
            st.write(source.title if source and source.title else current_archive.metadata.archive_id)
            st.caption(
                f"Domain: {current_archive.metadata.domain or 'unknown'} · "
                f"Source ID: {source.source_id if source else 'unavailable'}"
            )
            if source and source.doi:
                st.caption(f"DOI: {source.doi}")

        include_quarantined = st.toggle(
            "Include quarantined",
            value=False,
            help=(
                "Quarantined records remain explicitly marked and are never presented as canonical science."
            ),
            key="synthex_explorer_include_quarantined",
        )
        explorer = _cached_archive_explorer(
            current_archive.model_dump_json(exclude_none=True), include_quarantined,
        )
        if not explorer.results:
            _render_empty_results_state(current_archive, result_count=0)
        options = filter_options(explorer.results)

        search = st.text_input(
            "Search loaded results",
            placeholder="Material, metric, reaction, product, or evidence text",
            key="synthex_explorer_search",
            icon=":material/search:",
        )
        selected: dict[str, tuple[str, ...]] = {}
        filter_labels = (
            ("domain", "Domain"),
            ("source_title", "Source"),
            ("material_names", "Material"),
            ("experiment_type", "Experiment type"),
            ("reaction", "Reaction"),
            ("metric", "Metric"),
            ("product", "Product"),
            ("admission_status", "Admission status"),
            ("ownership", "Ownership"),
            ("evidence_origin", "Evidence origin"),
        )
        with st.expander("Filters", icon=":material/filter_alt:"):
            for start in range(0, len(filter_labels), 3):
                with st.container(horizontal=True):
                    for field, label in filter_labels[start:start + 3]:
                        values = options[field]
                        if values:
                            selected[field] = tuple(st.multiselect(
                                label,
                                values,
                                key=f"synthex_explorer_filter_{field}",
                                width="stretch",
                            ))
            estimated_choice = st.segmented_control(
                "Estimated status",
                ["All", "Estimated", "Not estimated"],
                default="All",
                key="synthex_explorer_estimated",
            ) if explorer.results else "All"
        estimated = True if estimated_choice == "Estimated" else False if estimated_choice == "Not estimated" else None
        filters = ExplorerFilters(
            **{field: selected.get(field, ()) for field, _ in filter_labels},
            estimated=estimated,
            search=search,
        )
        shown_results = filter_results(explorer.results, filters)

        result_tab, materials_tab, processes_tab, experiments_tab, calculations_tab, evidence_tab, relationships_tab = st.tabs(
            ["Results", "Materials", "Processes", "Experiments", "Calculations", "Evidence", "Relationships"]
        )
        with result_tab:
            st.caption(f"{len(shown_results)} observation(s) shown")
            if any(row.get("admission_status") == "quarantined" for row in shown_results):
                st.warning("This view includes quarantined records. Check admission status and rejection reason before use.")
            if shown_results:
                display_columns = (
                    "researcher_status", "admission_status", "material_names", "reaction", "experiment_type", "metric", "product",
                    "value", "unit", "temperature", "potential", "reference_electrode", "ownership",
                    "source_page", "evidence_origin",
                )
                highlighted_rows = result_highlights(shown_results, limit=len(shown_results))
                display_rows = [{key: row.get(key, "") for key in display_columns} for row in highlighted_rows]
                selection = st.dataframe(
                    display_rows,
                    hide_index=True,
                    column_order=display_columns,
                    key="synthex_explorer_results_table",
                    on_select="rerun",
                    selection_mode="single-row",
                )
                with st.container(horizontal=True):
                    st.download_button(
                        "Download filtered CSV",
                        data=export_results_rows_csv(shown_results),
                        file_name="filtered_results.csv",
                        mime="text/csv",
                        on_click="ignore",
                        icon=":material/download:",
                    )
                selected_rows = selection.selection.rows
                if selected_rows:
                    detail = highlighted_rows[selected_rows[0]]
                    with st.container(border=True):
                        st.write("Source tracking")
                        detail_fields = {
                            "Source title": detail.get("source_title"),
                            "DOI": detail.get("doi"),
                            "Page": detail.get("source_page"),
                            "Evidence origin": detail.get("evidence_origin"),
                            "Evidence strength": detail.get("evidence_strength"),
                            "Ownership": detail.get("ownership"),
                            "Admission status": detail.get("admission_status"),
                            "Estimated": detail.get("estimated"),
                            "Rejection reason": detail.get("quarantine_reason"),
                        }
                        st.table([{"Field": key, "Value": value or ""} for key, value in detail_fields.items()])
                        if detail.get("evidence_snippet"):
                            st.caption("Exact evidence snippet")
                            st.text(detail["evidence_snippet"])
                        with st.expander("Additional observation fields"):
                            st.json(detail)
            elif explorer.results:
                st.info("No observations match the current filters. Clear or broaden the filters to see the loaded results.")
            else:
                st.caption("No result rows are available for this archive; see the explanation above.")

        with materials_tab:
            if explorer.materials:
                st.dataframe(explorer.materials, hide_index=True)
            else:
                st.info("This archive contains no admitted materials.")
        with processes_tab:
            if explorer.processes:
                st.dataframe(explorer.processes, hide_index=True)
            else:
                st.info("This archive contains no admitted processes.")
        with experiments_tab:
            if explorer.experiments:
                st.dataframe(explorer.experiments, hide_index=True)
            else:
                st.info("This archive contains no admitted experiments.")
        with calculations_tab:
            if explorer.calculations:
                st.dataframe(explorer.calculations, hide_index=True)
            else:
                st.info("This archive contains no admitted calculations.")
        with evidence_tab:
            if explorer.evidence:
                st.dataframe(explorer.evidence, hide_index=True)
            else:
                st.info("This archive contains no attached evidence records.")
        with relationships_tab:
            if explorer.relationships:
                st.dataframe(explorer.relationships, hide_index=True)
            else:
                st.info("This archive contains no relationships.")

elif page == "Advanced · Diagnostics":
    st.subheader("Provider diagnostics")
    st.caption(
        "This optional check sends one tiny request to each configured Gemini model. "
        "Availability here does not guarantee that a full extraction will succeed."
    )
    st.write("Configured production order")
    st.code(" → ".join(configured_gemini_models()), language=None)
    if st.button("Run tiny provider check", type="primary"):
        try:
            with st.spinner("Checking configured models..."):
                st.session_state["synthex_provider_health"] = list(probe_configured_gemini())
        except (RuntimeError, ValueError) as exc:
            st.error(str(exc))
    provider_health = st.session_state.get("synthex_provider_health")
    if provider_health:
        st.dataframe(provider_health, hide_index=True, width="stretch")
        st.caption("No extraction, schema repair, Serper query, or archive mutation was performed.")

elif page == "Advanced · Knowledge graph":
    st.subheader("Knowledge graph export")
    archives = list(store.iter_archives() or [])
    if st.button("Build nodes.jsonl + edges.jsonl"):
        nodes, edges = export_graph(archives, "data/graph")
        st.success(f"Built {nodes} and {edges}")
    st.markdown("Graph relations include `processed_by`, `tested_in`, `calculated_for`, `has_property`, and `reported_by`.")

else:
    st.subheader("Gas Sensing V2")
    st.info("The existing Synthex V2 gas-sensing application remains available through `streamlit run streamlit_app.py`. V3 treats it as the first mature domain plugin rather than deleting it.")
