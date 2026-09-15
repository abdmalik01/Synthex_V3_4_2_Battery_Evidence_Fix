from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import zipfile

import streamlit as st

from synthex_platform.batch import MAX_BATCH_PAPERS, MIN_RESEARCH_BATCH, batch_source_summary, combined_result_rows, validate_batch_size
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
from synthex_platform.providers import GeminiModelsUnavailableError, configured_gemini_models, probe_configured_gemini
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


@st.cache_data(max_entries=32, show_spinner=False)
def _cached_archive_explorer(archive_json: str, include_quarantined: bool):
    return build_archive_explorer(
        SynthexArchive.model_validate_json(archive_json),
        include_quarantined=include_quarantined,
    )


def _navigate(destination: str) -> None:
    st.session_state["synthex_workspace"] = destination


def _session_archives() -> list[SynthexArchive]:
    batch = st.session_state.get("synthex_batch_archives") or []
    archives: list[SynthexArchive] = []
    for item in batch:
        try:
            archives.append(SynthexArchive.model_validate(item))
        except Exception:
            continue
    if archives:
        return archives
    single = st.session_state.get("synthex_last_archive")
    return [SynthexArchive.model_validate(single)] if single else []


def _archive_label(archive: SynthexArchive, index: int) -> str:
    source = archive.sources[0] if archive.sources else None
    title = source.title if source and source.title else archive.metadata.archive_id or f"Paper {index + 1}"
    return f"{index + 1}. {title}"


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


def _batch_json_zip(archives: list[SynthexArchive]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for index, archive in enumerate(archives, start=1):
            archive_id = archive.metadata.archive_id or f"paper_{index}"
            bundle.writestr(
                f"{archive_id}.json",
                archive.model_dump_json(indent=2, exclude_none=True),
            )
    return buffer.getvalue()


def _stop_worthy_provider_error(exc: Exception) -> bool:
    text = str(exc).casefold()
    return any(token in text for token in ("resource_exhausted", "quota", "429", "all configured gemini models"))


def _combined_records(archives: list[SynthexArchive], attribute: str, include_quarantined: bool) -> list[dict]:
    rows: list[dict] = []
    for archive in archives:
        explorer = _cached_archive_explorer(archive.model_dump_json(exclude_none=True), include_quarantined)
        source = archive.sources[0] if archive.sources else None
        source_title = source.title if source and source.title else archive.metadata.archive_id
        for item in getattr(explorer, attribute):
            row = dict(item)
            row.setdefault("source_title", source_title)
            rows.append(row)
    return rows


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
        "compared across papers, visualized, and exported."
    )
    with st.container(horizontal=True):
        st.button("Analyze papers", type="primary", icon=":material/upload_file:", on_click=_navigate, args=("Analyze Paper",))
        st.button("Discover papers", icon=":material/search:", on_click=_navigate, args=("Discover Papers",))
    st.subheader("What Synthex can do")
    capabilities = st.columns(3)
    with capabilities[0]:
        with st.container(border=True):
            st.write("Extract structured science")
            st.caption(f"Upload one paper or a research batch of up to {MAX_BATCH_PAPERS} PDFs. Each paper is routed and validated independently.")
    with capabilities[1]:
        with st.container(border=True):
            st.write("Keep evidence visible")
            st.caption("Track source, page, origin, ownership, admission, uncertainty, and quarantine for every paper.")
    with capabilities[2]:
        with st.container(border=True):
            st.write("Compare and export")
            st.caption("Pool admitted parameters across papers without mixing their source tracking.")
    st.subheader("Workspace status")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Domain plugins", len(registry.list_domains()))
    c2.metric("Saved archives", store.count())
    c3.metric("Benchmark tasks", sum(len(v) for v in benchmark_matrix(registry).values()))
    c4.metric("Batch capacity", f"{MAX_BATCH_PAPERS} PDFs")
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
        number_of_results = st.number_input("Results", min_value=1, max_value=10, value=5, step=1)
        submitted = st.form_submit_button("Search papers", type="primary", icon=":material/search:")
    if submitted:
        focus = None if focus_label == "No added focus" else focus_label
        try:
            with st.spinner("Searching paper discovery index..."):
                result = discover_papers(research_query, focus=focus, num_results=int(number_of_results))
            store_discovery_results(st.session_state, result)
        except DiscoveryError as exc:
            st.error(str(exc))
    if st.button("Clear search results", icon=":material/clear_all:"):
        clear_discovery_results(st.session_state)
    result = current_discovery_results(st.session_state)
    if result:
        usage = result.usage
        st.caption(
            f"Query: {result.query} · {'cache hit' if result.cache_hit else 'network query'} · "
            f"local network queries: {usage.get('network_queries', 0)} · remaining local budget: {usage.get('remaining_local_budget', 0)}"
        )
        if not result.candidates:
            st.info("No usable paper links were returned. Try a more specific materials-science query.")
        for candidate in result.candidates:
            with st.container(border=True):
                st.subheader(candidate.title)
                st.caption("Discovery result — not yet scientifically verified")
                if candidate.snippet:
                    st.write(candidate.snippet)
                if candidate.doi:
                    st.caption(f"DOI from direct DOI URL: {candidate.doi}")
                with st.container(horizontal=True):
                    st.link_button("Open paper link", candidate.url, icon=":material/open_in_new:")
                    already_saved = any(item.candidate_id == candidate.candidate_id for item in saved_discovery_candidates(st.session_state))
                    if st.button(
                        "Saved" if already_saved else "Save for extraction",
                        key=f"synthex_save_discovery_{candidate.candidate_id}",
                        disabled=already_saved,
                    ):
                        save_discovery_candidate(st.session_state, candidate)
    saved_candidates = saved_discovery_candidates(st.session_state)
    if saved_candidates:
        st.subheader("Saved for PDF upload")
        for candidate in saved_candidates:
            left, right = st.columns([4, 1])
            with left:
                st.write(candidate.title)
                st.link_button("Open paper link", candidate.url, key=f"saved_{candidate.candidate_id}")
            with right:
                if st.button("Remove", key=f"remove_{candidate.candidate_id}"):
                    remove_discovery_candidate(st.session_state, candidate.candidate_id)
        if st.button("Clear saved candidates"):
            clear_saved_discovery_candidates(st.session_state)

elif page == "Analyze Paper":
    st.subheader("Analyze scientific papers")
    st.caption("Upload → route each paper → extract independently → compare parameters → export")
    st.info(
        f"Batch extraction supports up to {MAX_BATCH_PAPERS} PDFs in one run, so literature sets of at least "
        f"{MIN_RESEARCH_BATCH} papers can be processed together. PDFs are never merged into one prompt; source tracking remains paper-specific."
    )
    st.caption("Auto Detect routes every uploaded paper independently. A manually selected domain is applied to the whole batch.")

    saved_candidates = saved_discovery_candidates(st.session_state)
    if saved_candidates:
        with st.expander("Saved discovery candidates"):
            st.caption("These are bibliography leads only; upload the real PDFs below.")
            for candidate in saved_candidates:
                st.write(candidate.title)

    options = {d["name"]: d["slug"] for d in registry.list_domains()}
    chosen_label = st.selectbox("Domain", ["Auto Detect"] + list(options), index=0)
    search_assisted = st.checkbox(
        "Search-assisted enrichment with Serper",
        value=False,
        help="Used only for bibliographic metadata/supplementary discovery; snippets never populate scientific measurements.",
    )
    find_supplementary = False
    if search_assisted:
        if os.getenv("SERPER_API_KEY"):
            find_supplementary = st.checkbox("Also search for supplementary/supporting information", value=False)
        else:
            st.warning("SERPER_API_KEY is not configured in .env. Search-assisted mode will fail until you add it.")

    uploaded_files = st.file_uploader(
        f"Upload PDFs — up to {MAX_BATCH_PAPERS} at once",
        type=["pdf"],
        accept_multiple_files=True,
        key="synthex_pdf_batch",
    )
    if uploaded_files:
        st.caption(f"Selected {len(uploaded_files)} paper(s): " + ", ".join(file.name for file in uploaded_files))
        try:
            validate_batch_size(len(uploaded_files))
        except ValueError as exc:
            st.error(str(exc))
        else:
            if len(uploaded_files) >= MIN_RESEARCH_BATCH:
                st.success(f"Research batch ready: {len(uploaded_files)} papers selected.")
            if len(uploaded_files) > 1:
                st.warning(
                    "Each PDF can require one or more Gemini calls. Free-tier provider quotas may stop a large batch part-way through. "
                    "Synthex preserves completed papers and reports unresolved papers instead of discarding the batch."
                )
            button_label = "Extract research record" if len(uploaded_files) == 1 else f"Extract {len(uploaded_files)} papers"
            if st.button(button_label, type="primary"):
                domain = "auto" if chosen_label == "Auto Detect" else options[chosen_label]
                completed: list[dict] = []
                statuses: list[dict] = []
                progress = st.progress(0, text="Preparing batch...")
                stop_batch = False
                for index, uploaded in enumerate(uploaded_files):
                    progress.progress(index / len(uploaded_files), text=f"Processing {index + 1}/{len(uploaded_files)} · {uploaded.name}")
                    pipeline = SynthexExtractionPipeline(
                        router=router,
                        search_assisted=search_assisted,
                        find_supplementary=find_supplementary,
                    )
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded.getbuffer())
                        tmp_path = Path(tmp.name)
                    try:
                        bundle = pipeline.build_source_bundle(tmp_path, source_filename=uploaded.name)
                        resolved_route, archive = pipeline.extract_source_bundle(bundle, domain=domain)
                    except (StructuredExtractionValidationError, CatalysisStructuredExtractionValidationError) as exc:
                        statuses.append({
                            "file": uploaded.name,
                            "status": "validation_failed",
                            "domain": getattr(exc, "route", None),
                            "message": str(exc),
                        })
                    except GeminiModelsUnavailableError as exc:
                        statuses.append({
                            "file": uploaded.name,
                            "status": "provider_blocked",
                            "domain": None,
                            "message": str(exc),
                        })
                        stop_batch = True
                    except Exception as exc:
                        statuses.append({
                            "file": uploaded.name,
                            "status": "provider_blocked" if _stop_worthy_provider_error(exc) else "failed",
                            "domain": None,
                            "message": str(exc),
                        })
                        stop_batch = _stop_worthy_provider_error(exc)
                    else:
                        archive_data = archive.model_dump(exclude_none=True)
                        completed.append(archive_data)
                        statuses.append({
                            "file": uploaded.name,
                            "status": "complete",
                            "domain": resolved_route.domain,
                            "archive_id": archive.metadata.archive_id,
                            "message": "",
                        })
                    finally:
                        tmp_path.unlink(missing_ok=True)
                    if stop_batch:
                        for remaining in uploaded_files[index + 1:]:
                            statuses.append({
                                "file": remaining.name,
                                "status": "not_attempted",
                                "domain": None,
                                "message": "Batch stopped after provider/quota blockage to avoid wasting calls.",
                            })
                        break
                progress.progress(1.0, text="Batch processing finished")
                st.session_state["synthex_batch_archives"] = completed
                st.session_state["synthex_batch_status"] = statuses
                if completed:
                    st.session_state["synthex_last_archive"] = completed[-1]
                    st.session_state["synthex_last_route"] = completed[-1].get("metadata", {}).get("domain")

    batch_status = st.session_state.get("synthex_batch_status") or []
    archives = _session_archives()
    if batch_status:
        st.subheader("Batch status")
        st.dataframe(batch_status, hide_index=True, width="stretch")
    if archives:
        if len(archives) > 1:
            st.success(f"{len(archives)} paper archives are ready for cross-paper comparison.")
            summaries = batch_source_summary(archives)
            st.dataframe(summaries, hide_index=True, width="stretch")
            include_quarantined_batch = st.checkbox(
                "Include quarantined records in combined export",
                value=False,
                key="synthex_batch_include_quarantined",
            )
            combined_rows = combined_result_rows(archives, include_quarantined=include_quarantined_batch)
            st.metric("Combined observations", len(combined_rows))
            with st.container(horizontal=True):
                st.download_button(
                    "Download combined CSV",
                    export_results_rows_csv(combined_rows),
                    "synthex_batch_results.csv",
                    "text/csv",
                    icon=":material/table_view:",
                )
                st.download_button(
                    "Download batch JSON ZIP",
                    _batch_json_zip(archives),
                    "synthex_batch_archives.zip",
                    "application/zip",
                    icon=":material/folder_zip:",
                )
                if st.button("Save successful batch to local Synthex Archive"):
                    for archive in archives:
                        store.append(archive)
                    st.success(f"Saved {len(archives)} archives to data/archive/archives.jsonl")
            st.button("Explore combined results", type="primary", on_click=_navigate, args=("Explore Results",))

        selected_index = 0
        if len(archives) > 1:
            selected_label = st.selectbox(
                "Inspect one paper",
                [_archive_label(archive, index) for index, archive in enumerate(archives)],
                key="synthex_batch_inspect",
            )
            selected_index = [_archive_label(archive, index) for index, archive in enumerate(archives)].index(selected_label)
        archive = archives[selected_index]
        if len(archives) == 1:
            st.success(f"Latest extraction complete · {archive.metadata.domain or 'unknown'}")
        _render_archive_summary(archive)
        explorer = _cached_archive_explorer(archive.model_dump_json(exclude_none=True), False)
        highlights = result_highlights(explorer.results)
        if highlights:
            st.write("Result highlights")
            for highlight in highlights[:8]:
                label = highlight.get("metric") or highlight.get("experiment_type") or "Scientific observation"
                value = " ".join(str(item) for item in (highlight.get("value"), highlight.get("unit")) if item not in (None, ""))
                with st.container(border=True):
                    st.write(f"{label}: {value or 'Recorded'}")
                    st.caption(f"page {highlight.get('source_page') or 'not resolved'} · evidence {highlight.get('evidence_origin') or 'not recorded'}")
        else:
            _render_empty_results_state(archive, result_count=0)
        archive_id = archive.metadata.archive_id or "synthex_record"
        with st.expander("Complete validated archive"):
            st.json(archive.model_dump(exclude_none=True))
        with st.container(horizontal=True):
            st.download_button("Download JSON", archive.model_dump_json(indent=2, exclude_none=True), f"{archive_id}.json", "application/json")
            st.download_button("Download CSV", export_results_csv(archive), "results.csv", "text/csv")
            st.download_button("Download CSV Bundle", export_csv_bundle_zip(archive), f"{archive_id}_csv_bundle.zip", "application/zip")
        if len(archives) == 1:
            st.button("Explore all results", type="primary", on_click=_navigate, args=("Explore Results",))
            if st.button("Save latest extraction to local Synthex Archive"):
                store.append(archive)
                st.success("Saved to data/archive/archives.jsonl")

elif page == "Explore Results":
    st.subheader("Explore Results")
    st.caption("Compare structured parameters across the current extraction batch while preserving paper-level source tracking.")
    archives = _session_archives()
    if not archives:
        st.info("No current extraction to explore. Extract one or more papers first, then return here.")
    else:
        if len(archives) > 1:
            st.success(f"Cross-paper workspace · {len(archives)} successfully extracted papers")
            st.dataframe(batch_source_summary(archives), hide_index=True, width="stretch")
        selection_options = ["All successful papers"] if len(archives) > 1 else []
        selection_options += [_archive_label(archive, i) for i, archive in enumerate(archives)]
        selected_scope = st.selectbox("Result scope", selection_options, index=0, key="synthex_explorer_scope")
        if selected_scope == "All successful papers":
            scoped_archives = archives
        else:
            chosen_idx = [_archive_label(archive, i) for i, archive in enumerate(archives)].index(selected_scope)
            scoped_archives = [archives[chosen_idx]]
            _render_archive_summary(scoped_archives[0])

        include_quarantined = st.toggle(
            "Include quarantined",
            value=False,
            help="Quarantined records remain explicitly marked and are never presented as canonical science.",
            key="synthex_explorer_include_quarantined",
        )
        all_results = combined_result_rows(scoped_archives, include_quarantined=include_quarantined)
        if not all_results:
            for archive in scoped_archives:
                _render_empty_results_state(archive, result_count=0)

        options = filter_options(all_results)
        search = st.text_input(
            "Search loaded results",
            placeholder="Paper, material, metric, reaction, product, or evidence text",
            key="synthex_explorer_search",
            icon=":material/search:",
        )
        selected: dict[str, tuple[str, ...]] = {}
        filter_labels = (
            ("domain", "Domain"),
            ("source_title", "Paper"),
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
                cols = st.columns(min(3, len(filter_labels[start:start + 3])))
                for col, (field, label) in zip(cols, filter_labels[start:start + 3]):
                    values = options.get(field, [])
                    if values:
                        with col:
                            selected[field] = tuple(st.multiselect(label, values, key=f"filter_{field}"))
            estimated_choice = st.segmented_control(
                "Estimated status", ["All", "Estimated", "Not estimated"], default="All", key="synthex_explorer_estimated"
            ) if all_results else "All"
        estimated = True if estimated_choice == "Estimated" else False if estimated_choice == "Not estimated" else None
        filters = ExplorerFilters(
            **{field: selected.get(field, ()) for field, _ in filter_labels},
            estimated=estimated,
            search=search,
        )
        shown_results = filter_results(all_results, filters)

        result_tab, materials_tab, processes_tab, experiments_tab, calculations_tab, evidence_tab, relationships_tab = st.tabs(
            ["Results", "Materials", "Processes", "Experiments", "Calculations", "Evidence", "Relationships"]
        )
        with result_tab:
            st.caption(f"{len(shown_results)} observation(s) shown across {len(scoped_archives)} paper(s)")
            if any(row.get("admission_status") == "quarantined" for row in shown_results):
                st.warning("This view includes quarantined records. Check admission status and rejection reason before use.")
            if shown_results:
                display_columns = (
                    "source_title", "researcher_status", "admission_status", "material_names", "reaction", "experiment_type", "metric", "product",
                    "value", "unit", "temperature", "potential", "reference_electrode", "ownership", "source_page", "evidence_origin",
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
                    width="stretch",
                )
                st.download_button(
                    "Download filtered cross-paper CSV",
                    export_results_rows_csv(shown_results),
                    "filtered_cross_paper_results.csv",
                    "text/csv",
                    icon=":material/download:",
                )
                if selection.selection.rows:
                    detail = highlighted_rows[selection.selection.rows[0]]
                    with st.container(border=True):
                        st.write("Source tracking")
                        detail_fields = {
                            "Paper": detail.get("source_title"),
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
            elif all_results:
                st.info("No observations match the current filters. Clear or broaden the filters.")
            else:
                st.caption("No result rows are available for the selected paper scope; see the explanation above.")

        for tab, attribute, empty_text in (
            (materials_tab, "materials", "No admitted materials in the selected paper scope."),
            (processes_tab, "processes", "No admitted processes in the selected paper scope."),
            (experiments_tab, "experiments", "No admitted experiments in the selected paper scope."),
            (calculations_tab, "calculations", "No admitted calculations in the selected paper scope."),
            (evidence_tab, "evidence", "No attached evidence records in the selected paper scope."),
            (relationships_tab, "relationships", "No relationships in the selected paper scope."),
        ):
            with tab:
                records = _combined_records(scoped_archives, attribute, include_quarantined)
                if records:
                    st.dataframe(records, hide_index=True, width="stretch")
                else:
                    st.info(empty_text)

elif page == "Visualize Data":
    st.subheader("Visual Explorer")
    saved_archives = list(store.iter_archives() or [])
    current_archives = _session_archives()
    by_id = {archive.metadata.archive_id: archive for archive in saved_archives if archive.metadata.archive_id}
    for archive in current_archives:
        by_id[archive.metadata.archive_id or f"session-{id(archive)}"] = archive
    archives = list(by_id.values())
    all_rows = project_archives(archives)
    properties = sorted({row.property_name for row in all_rows})
    if not properties:
        st.info("No canonical numeric archive measurements are available to visualize.")
    else:
        property_name = st.selectbox("Property", properties)
        rows = project_archives(archives, AnalyticQuery(property_name=property_name))
        frame = comparison_frame(rows)
        st.caption("Current batch and saved archives can be compared. Source/archive identifiers remain attached to the projected rows.")
        st.dataframe(frame, hide_index=True, width="stretch")
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

elif page == "Advanced · Battery validation":
    st.subheader("Batteries V1.3 validation corpus")
    st.info("Benchmark runs are paper-only by design: Serper enrichment is OFF during scoring so retrieval cannot leak answers into extraction benchmarks.")
    manifest_path = Path("benchmark/batteries_v1/corpus_manifest.json")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        a, b, c, d = st.columns(4)
        a.metric("Files", manifest.get("total_files", 0))
        b.metric("Unique", manifest.get("unique_files", 0))
        c.metric("Battery-relevant", manifest.get("battery_relevant_unique", 0))
        d.metric("Negative controls", manifest.get("negative_controls", 0))
        rows = [x for x in manifest.get("entries", []) if x.get("benchmark_priority") != "EXCLUDE"]
        st.dataframe(rows, width="stretch")
    st.markdown("**Primary gold benchmark:** `batteries-11-00142.pdf` (Li2FeTiO4 sol–gel cathode).")
    st.code('python benchmark_battery_material.py "path/to/batteries-11-00142.pdf"', language="powershell")

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
    for domain, tasks in benchmark_matrix(registry).items():
        with st.expander(f"{registry.get(domain)['name']} · {len(tasks)} tasks"):
            for task in tasks:
                st.write("•", task)

elif page == "Advanced · Figure Data":
    st.subheader("Digitized figures")
    st.caption("Sidecar-only estimates. Confirm calibration before a dataset can be completed; no values are added to the canonical archive.")
    image_file = st.file_uploader("Rendered figure or selected panel PNG", type=["png"], key="digitization_png")
    if image_file:
        from PIL import Image
        image_bytes = image_file.getvalue()
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size
        st.image(image_bytes, caption=f"{width} × {height} px")
        with st.form("digitization_calibration"):
            source_id = st.text_input("Source ID", value="source-figure")
            figure_id = st.text_input("Figure ID", value="fig-selected")
            panel = st.text_input("Panel label (optional)") or None
            plot_x0 = st.number_input("Plot left pixel", min_value=0.0, value=0.0)
            plot_y0 = st.number_input("Plot top pixel", min_value=0.0, value=0.0)
            plot_x1 = st.number_input("Plot right pixel", min_value=1.0, value=float(width))
            plot_y1 = st.number_input("Plot bottom pixel", min_value=1.0, value=float(height))
            x0 = st.number_input("X value at left", value=0.0)
            x1 = st.number_input("X value at right", value=1.0)
            y0 = st.number_input("Y value at bottom", value=0.0)
            y1 = st.number_input("Y value at top", value=1.0)
            x_log = st.checkbox("X axis is log10")
            y_log = st.checkbox("Y axis is log10")
            red = st.text_input("Selected series RGB", value="228,26,28")
            submitted = st.form_submit_button("Confirm calibration and digitize", type="primary")
        if submitted:
            try:
                rgb = tuple(int(value.strip()) for value in red.split(","))
                request = DigitizationRequest(
                    source_id=source_id,
                    page=1,
                    figure_id=figure_id,
                    panel=panel,
                    plot_area=PlotArea(bbox=PixelBoundingBox(x0=plot_x0, y0=plot_y0, x1=plot_x1, y1=plot_y1), resolution_width=width, resolution_height=height),
                    x_axis=AxisCalibration(axis="x", pixel_start=plot_x0, pixel_end=plot_x1, data_start=x0, data_end=x1, scale_type="log10" if x_log else "linear"),
                    y_axis=AxisCalibration(axis="y", pixel_start=plot_y1, pixel_end=plot_y0, data_start=y0, data_end=y1, scale_type="log10" if y_log else "linear"),
                    series=[SeriesSelection(series_id="series-user", color_rgb=rgb, association_status="ambiguous")],
                )
                result = digitize_plot(image_bytes, request)
                if result.status == "completed":
                    st.success(f"Digitized {sum(len(series.points) for series in result.series)} estimated points.")
                    st.download_button("Download digitized JSON", result.model_dump_json(indent=2), f"{result.digitization_id}.json", "application/json")
                else:
                    st.warning("Digitization was rejected: " + "; ".join(result.rejection_reasons))
            except (ValueError, TypeError) as error:
                st.error(f"Calibration was not accepted: {error}")

elif page == "Advanced · Diagnostics":
    st.subheader("Provider diagnostics")
    st.caption("This optional check sends one tiny request to each configured Gemini model. Availability here does not guarantee that a full extraction will succeed.")
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
