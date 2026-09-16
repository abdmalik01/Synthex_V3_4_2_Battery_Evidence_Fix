from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path
import tempfile
import zipfile

import streamlit as st

from synthex_platform.batch import (
    MAX_BATCH_PAPERS,
    MIN_RESEARCH_BATCH,
    batch_source_summary,
    combined_result_rows,
    validate_batch_size,
)
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
from synthex_platform.gas_sensing_ui import render_gas_sensing_analytics
from synthex_platform.graph import export_graph
from synthex_platform.graph_extraction_ui import render_graph_extraction_ui
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
from synthex_platform.ui_errors import PublicErrorNotice, is_server_busy_error, public_error_notice
from synthex_platform.ui_navigation import developer_mode_enabled, navigation_items
from synthex_platform.ui_session import clear_research_workspace
from synthex_platform.visual.analytics import AnalyticQuery, build_visualization_spec, comparison_frame, project_archives
from synthex_platform.visual.analytics.render import VisualizationRenderer

st.set_page_config(page_title="Synthex · Materials Intelligence", page_icon="🧬", layout="wide")

logger = logging.getLogger("synthex.ui")
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


def _start_new_analysis() -> None:
    clear_research_workspace(st.session_state)
    st.session_state["synthex_workspace"] = "Analyze Papers"


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


def _record_ui_error(context: str, exc: Exception) -> None:
    """Keep technical failures in backend logs instead of the public Streamlit UI."""
    logger.exception("Synthex UI operation failed [%s]: %s", context, exc)


def _render_public_notice(notice: PublicErrorNotice) -> None:
    body = f"**{notice.title}**\n\n{notice.message}"
    if notice.status == "server_busy":
        st.warning(body)
    else:
        st.info(body)


def _stop_worthy_provider_error(exc: Exception) -> bool:
    return is_server_busy_error(exc)


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


DEVELOPER_MODE = developer_mode_enabled()
NAVIGATION = navigation_items(developer_mode=DEVELOPER_MODE)
if st.session_state.get("synthex_workspace") not in NAVIGATION:
    st.session_state["synthex_workspace"] = "Home"

st.sidebar.title("SYNTHEX")
st.sidebar.caption("Materials intelligence workspace")
page = st.sidebar.radio("Workspace", NAVIGATION, key="synthex_workspace")
if DEVELOPER_MODE:
    st.sidebar.caption("Developer mode enabled")


if page == "Home":
    st.title("SYNTHEX")
    st.subheader("Materials Intelligence from Scientific Literature")
    st.write(
        "Turn scientific papers into source-tracked materials data that can be reviewed, "
        "compared across papers, visualized, and exported."
    )
    with st.container(horizontal=True):
        st.button("Analyze papers", type="primary", icon=":material/upload_file:", on_click=_navigate, args=("Analyze Papers",))
        st.button("Discover papers", icon=":material/search:", on_click=_navigate, args=("Discover Papers",))

    st.subheader("What Synthex can do")
    capabilities = st.columns(3)
    with capabilities[0]:
        with st.container(border=True):
            st.write("Extract structured science")
            st.caption(
                f"Upload one paper or a literature batch of up to {MAX_BATCH_PAPERS} PDFs. "
                "Each paper is routed and validated independently."
            )
    with capabilities[1]:
        with st.container(border=True):
            st.write("Keep source tracking visible")
            st.caption("Preserve paper, page, ownership, admission status, uncertainty, and evidence context.")
    with capabilities[2]:
        with st.container(border=True):
            st.write("Compare and export")
            st.caption("Pool admitted parameters across papers without mixing the identity of their sources.")

    c1, c2 = st.columns(2)
    c1.metric("Scientific domains", len(registry.list_domains()))
    c2.metric("Batch capacity", f"{MAX_BATCH_PAPERS} PDFs")


elif page == "Discover Papers":
    st.subheader("Discover materials-science papers")
    st.caption(
        "Search results are navigation metadata only. Search snippets never become scientific evidence or canonical archive data."
    )
    with st.form("paper_discovery_form", border=False):
        research_query = st.text_input(
            "Research query",
            placeholder="e.g. NiFe LDH OER catalyst, ZnO NO2 sensing, LiFePO4 cathode synthesis",
            key="synthex_discovery_query_input",
        )
        focus_label = st.selectbox(
            "Optional focus",
            ["No added focus", "Materials science", "Battery materials", "Catalysis and electrocatalysis", "Gas sensing"],
            key="synthex_discovery_focus",
        )
        number_of_results = st.number_input(
            "Results", min_value=1, max_value=10, value=5, step=1, key="synthex_discovery_result_count"
        )
        submitted = st.form_submit_button("Search papers", type="primary", icon=":material/search:")

    if submitted:
        focus = None if focus_label == "No added focus" else focus_label
        try:
            with st.spinner("Searching paper discovery index..."):
                result = discover_papers(research_query, focus=focus, num_results=int(number_of_results))
            store_discovery_results(st.session_state, result)
        except DiscoveryError as exc:
            _record_ui_error("paper_discovery", exc)
            _render_public_notice(public_error_notice(exc, context="discovery"))

    if st.button("Clear search results", icon=":material/clear_all:"):
        clear_discovery_results(st.session_state)

    result = current_discovery_results(st.session_state)
    if result:
        usage = result.usage
        st.caption(
            f"Query: {result.query} · {'cache hit' if result.cache_hit else 'network query'} · "
            f"local network queries: {usage.get('network_queries', 0)} · "
            f"remaining local budget: {usage.get('remaining_local_budget', 0)}"
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
                    already_saved = any(
                        item.candidate_id == candidate.candidate_id
                        for item in saved_discovery_candidates(st.session_state)
                    )
                    if st.button(
                        "Saved" if already_saved else "Save for extraction",
                        key=f"synthex_save_discovery_{candidate.candidate_id}",
                        disabled=already_saved,
                    ):
                        save_discovery_candidate(st.session_state, candidate)

    saved_candidates = saved_discovery_candidates(st.session_state)
    if saved_candidates:
        st.subheader("Saved for PDF upload")
        st.caption("Saved discovery candidates remain bibliography leads until the actual PDF is uploaded and analyzed.")
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


elif page == "Analyze Papers":
    top_left, top_right = st.columns([5, 1])
    with top_left:
        st.subheader("Analyze scientific papers")
    with top_right:
        st.button(
            "Start new analysis",
            icon=":material/restart_alt:",
            on_click=_start_new_analysis,
            help=(
                "Clear current uploads, batch status, filters, and in-session extraction results. "
                "Saved archives and discovery leads are kept."
            ),
            width="stretch",
        )

    st.caption("Upload → route each paper → extract independently → compare parameters → export")
    st.info(
        f"Upload up to {MAX_BATCH_PAPERS} PDFs in one batch. Papers are never merged into one extraction prompt; "
        "source tracking remains paper-specific."
    )

    saved_candidates = saved_discovery_candidates(st.session_state)
    if saved_candidates:
        with st.expander("Saved discovery candidates"):
            st.caption("These are bibliography leads only; upload the actual PDFs below.")
            for candidate in saved_candidates:
                st.write(candidate.title)

    options = {item["name"]: item["slug"] for item in registry.list_domains()}
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
            st.info("Search-assisted enrichment is temporarily unavailable on this installation.")

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
            _record_ui_error("batch_selection", exc)
            _render_public_notice(public_error_notice(exc, context="batch_selection"))
        else:
            if len(uploaded_files) >= MIN_RESEARCH_BATCH:
                st.success(f"Research batch ready: {len(uploaded_files)} papers selected.")
            if len(uploaded_files) > 1:
                st.warning(
                    "Large batches may pause if the processing service becomes busy. "
                    "Completed papers are preserved so you can safely retry the remainder."
                )
            button_label = "Extract research record" if len(uploaded_files) == 1 else f"Extract {len(uploaded_files)} papers"
            if st.button(button_label, type="primary"):
                domain = "auto" if chosen_label == "Auto Detect" else options[chosen_label]
                completed: list[dict] = []
                statuses: list[dict] = []
                progress = st.progress(0, text="Preparing batch...")
                stop_batch = False

                for index, uploaded in enumerate(uploaded_files):
                    progress.progress(
                        index / len(uploaded_files),
                        text=f"Processing {index + 1}/{len(uploaded_files)} · {uploaded.name}",
                    )
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
                        _record_ui_error("paper_extraction_validation", exc)
                        notice = public_error_notice(exc, context="extraction_validation")
                        statuses.append({
                            "file": uploaded.name,
                            "status": notice.status,
                            "domain": getattr(exc, "route", None),
                            "message": notice.message,
                        })
                    except GeminiModelsUnavailableError as exc:
                        _record_ui_error("gemini_models_unavailable", exc)
                        notice = public_error_notice(exc, force_server_busy=True)
                        statuses.append({
                            "file": uploaded.name,
                            "status": notice.status,
                            "domain": None,
                            "message": f"{notice.title} — {notice.message}",
                        })
                        stop_batch = True
                    except Exception as exc:
                        _record_ui_error("paper_extraction_unexpected", exc)
                        stop_batch = _stop_worthy_provider_error(exc)
                        notice = public_error_notice(exc, force_server_busy=stop_batch)
                        statuses.append({
                            "file": uploaded.name,
                            "status": notice.status,
                            "domain": None,
                            "message": f"{notice.title} — {notice.message}" if notice.status == "server_busy" else notice.message,
                        })
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
                                "message": "Not processed because the service became busy. Please try again shortly.",
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
        if any(item.get("status") == "server_busy" for item in batch_status):
            _render_public_notice(public_error_notice(force_server_busy=True))
        st.subheader("Batch status")
        display_statuses = []
        status_labels = {
            "complete": "Complete",
            "server_busy": "Server Busy",
            "could_not_complete": "Please retry",
            "not_attempted": "Not processed",
        }
        for item in batch_status:
            display_item = dict(item)
            display_item["status"] = status_labels.get(str(item.get("status", "")), "Please retry")
            display_statuses.append(display_item)
        st.dataframe(display_statuses, hide_index=True, width="stretch")

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
            labels = [_archive_label(archive, index) for index, archive in enumerate(archives)]
            selected_label = st.selectbox("Inspect one paper", labels, key="synthex_batch_inspect")
            selected_index = labels.index(selected_label)

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
                value = " ".join(
                    str(item)
                    for item in (highlight.get("value"), highlight.get("unit"))
                    if item not in (None, "")
                )
                with st.container(border=True):
                    st.write(f"{label}: {value or 'Recorded'}")
                    st.caption(
                        f"page {highlight.get('source_page') or 'not resolved'} · "
                        f"evidence {highlight.get('evidence_origin') or 'not recorded'}"
                    )
        else:
            _render_empty_results_state(archive, result_count=0)

        archive_id = archive.metadata.archive_id or "synthex_record"
        with st.expander("Complete validated archive"):
            st.json(archive.model_dump(exclude_none=True))
        with st.container(horizontal=True):
            st.download_button(
                "Download JSON",
                archive.model_dump_json(indent=2, exclude_none=True),
                f"{archive_id}.json",
                "application/json",
            )
            st.download_button("Download CSV", export_results_csv(archive), "results.csv", "text/csv")
            st.download_button(
                "Download CSV Bundle",
                export_csv_bundle_zip(archive),
                f"{archive_id}_csv_bundle.zip",
                "application/zip",
            )

        if len(archives) == 1:
            st.button("Explore all results", type="primary", on_click=_navigate, args=("Explore Results",))
            if st.button("Save latest extraction to local Synthex Archive"):
                store.append(archive)
                st.success("Saved to data/archive/archives.jsonl")


elif page == "Explore Results":
    top_left, top_right = st.columns([5, 1])
    with top_left:
        st.subheader("Explore Results")
    with top_right:
        st.button(
            "Start new analysis",
            icon=":material/restart_alt:",
            on_click=_start_new_analysis,
            help="Clear the current in-session paper/batch and return to a fresh uploader. Saved archives are not deleted.",
            width="stretch",
        )

    st.caption("Compare structured parameters across the current extraction batch while preserving paper-level source tracking.")
    archives = _session_archives()
    if not archives:
        st.info("No current extraction to explore. Extract one or more papers first, then return here.")
    else:
        if len(archives) > 1:
            st.success(f"Cross-paper workspace · {len(archives)} successfully extracted papers")
            st.dataframe(batch_source_summary(archives), hide_index=True, width="stretch")

        selection_options = ["All successful papers"] if len(archives) > 1 else []
        selection_options += [_archive_label(archive, index) for index, archive in enumerate(archives)]
        selected_scope = st.selectbox("Result scope", selection_options, index=0, key="synthex_explorer_scope")

        if selected_scope == "All successful papers":
            scoped_archives = archives
        else:
            labels = [_archive_label(archive, index) for index, archive in enumerate(archives)]
            scoped_archives = [archives[labels.index(selected_scope)]]
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
                group = filter_labels[start:start + 3]
                cols = st.columns(len(group))
                for col, (field, label) in zip(cols, group):
                    values = options.get(field, [])
                    if values:
                        with col:
                            selected[field] = tuple(st.multiselect(label, values, key=f"filter_{field}"))
            estimated_choice = (
                st.segmented_control(
                    "Estimated status",
                    ["All", "Estimated", "Not estimated"],
                    default="All",
                    key="synthex_explorer_estimated",
                )
                if all_results
                else "All"
            )

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
                    "source_title",
                    "researcher_status",
                    "admission_status",
                    "material_names",
                    "reaction",
                    "experiment_type",
                    "metric",
                    "product",
                    "value",
                    "unit",
                    "temperature",
                    "potential",
                    "reference_electrode",
                    "ownership",
                    "source_page",
                    "evidence_origin",
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
    from synthex_platform.visual.analytics.streamlit_panel import render_visual_explorer

    saved_archives = list(store.iter_archives() or [])
    current_archives = _session_archives()
    by_id = {archive.metadata.archive_id: archive for archive in saved_archives if archive.metadata.archive_id}
    for archive in current_archives:
        by_id[archive.metadata.archive_id or f"session-{id(archive)}"] = archive
    render_visual_explorer(list(by_id.values()))


elif page == "Gas Sensing Analytics":
    render_gas_sensing_analytics()


elif page == "Extract Data from Graphs":
    render_graph_extraction_ui()


elif page == "Developer · Battery validation":
    st.subheader("Batteries V1.3 validation corpus")
    st.info("Developer-only benchmark view. Serper enrichment remains off during scoring.")
    manifest_path = Path("benchmark/batteries_v1/corpus_manifest.json")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        a, b, c, d = st.columns(4)
        a.metric("Files", manifest.get("total_files", 0))
        b.metric("Unique", manifest.get("unique_files", 0))
        c.metric("Battery-relevant", manifest.get("battery_relevant_unique", 0))
        d.metric("Negative controls", manifest.get("negative_controls", 0))
        rows = [item for item in manifest.get("entries", []) if item.get("benchmark_priority") != "EXCLUDE"]
        st.dataframe(rows, width="stretch")
    st.markdown("**Primary gold benchmark:** `batteries-11-00142.pdf` (Li2FeTiO4 sol–gel cathode).")


elif page == "Developer · Benchmark catalog":
    st.subheader("Benchmark catalog")
    for domain, tasks in benchmark_matrix(registry).items():
        with st.expander(f"{registry.get(domain)['name']} · {len(tasks)} tasks"):
            for task in tasks:
                st.write("•", task)


elif page == "Developer · Diagnostics":
    st.subheader("Provider diagnostics")
    st.caption(
        "This developer check sends one tiny request to each configured Gemini model. "
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


elif page == "Developer · Domain registry":
    st.subheader("Scientific domain registry")
    options = {item["name"]: item["slug"] for item in registry.list_domains()}
    chosen = st.selectbox("Domain", list(options))
    spec = registry.get(options[chosen])
    st.write(spec["description"])
    maturity = {
        "gas_sensing": "Mature gas-sensing extraction and analytics domain",
        "batteries": "Frozen Batteries V1.3 scientific domain",
        "catalysis": "Catalysis/Electrocatalysis Stage 3 closed; Stage 4 freeze pending",
    }.get(options[chosen], "Platform scaffold; not yet benchmark-validated")
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


elif page == "Developer · Knowledge graph":
    st.subheader("Knowledge graph export")
    archives = list(store.iter_archives() or [])
    if st.button("Build nodes.jsonl + edges.jsonl"):
        nodes, edges = export_graph(archives, "data/graph")
        st.success(f"Built {nodes} and {edges}")
    st.markdown("Graph relations include `processed_by`, `tested_in`, `calculated_for`, `has_property`, and `reported_by`.")