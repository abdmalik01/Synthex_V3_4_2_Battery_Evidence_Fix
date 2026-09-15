from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from search import search_papers
from synthex_platform.batch import MAX_BATCH_PAPERS, validate_batch_size
from synthex_v2.batch import merge_records
from synthex_v2.extractor import GeminiSensorExtractor
from synthex_v2.exporters import flatten_record, to_json_bytes
from synthex_v2.models import SensorRecord
from synthex_v2.visualizations import (
    figure_to_png_bytes,
    plot_radar,
    radar_groups,
    plot_response_time_contour,
    plot_selectivity_heatmap,
    response_time_groups,
    response_time_points,
    selectivity_matrix,
)

_RECORD_KEY = "synthex_gas_record"
_WARNINGS_KEY = "synthex_gas_warnings"


def _clear_gas_workspace() -> None:
    for key in (
        _RECORD_KEY,
        _WARNINGS_KEY,
        "synthex_gas_uploads",
        "synthex_gas_extraction_mode",
        "synthex_gas_category",
        "synthex_gas_search_category",
        "synthex_gas_search_focus",
    ):
        st.session_state.pop(key, None)


def _ensure_state() -> None:
    st.session_state.setdefault(_RECORD_KEY, None)
    st.session_state.setdefault(_WARNINGS_KEY, [])


def render_gas_sensing_analytics() -> None:
    """Render Synthex's native gas-sensing extraction and analytics workspace."""
    _ensure_state()

    top_left, top_right = st.columns([5, 1])
    with top_left:
        st.subheader("Gas Sensing Analytics")
        st.caption(
            "Extract synthesis, deposition, sensing conditions, performance and source-tracked evidence, "
            "then compare gas-sensor materials across papers."
        )
    with top_right:
        st.button(
            "Start new analysis",
            key="synthex_gas_reset",
            icon=":material/restart_alt:",
            on_click=_clear_gas_workspace,
            width="stretch",
        )

    setup, results = st.tabs(["Extract papers", "Analytics & export"])

    with setup:
        left, right = st.columns(2)
        with left:
            extraction_mode = st.selectbox(
                "Extraction mode",
                ["Full Sensor Record", "Synthesis + Deposition", "Sensor Performance"],
                key="synthex_gas_extraction_mode",
            )
        with right:
            category = st.selectbox(
                "Material category",
                [
                    "Auto Detect",
                    "Metal Oxides",
                    "Metal Sulfides",
                    "Metal-Organic Frameworks",
                    "Carbon-based",
                    "Polymeric Nanomaterials",
                    "Pure Metals / Alloys",
                ],
                key="synthex_gas_category",
            )

        uploads = st.file_uploader(
            f"Upload gas-sensing research PDFs — up to {MAX_BATCH_PAPERS} at once",
            type=["pdf"],
            accept_multiple_files=True,
            key="synthex_gas_uploads",
        )
        if uploads:
            st.caption(f"Selected {len(uploads)} paper(s): " + ", ".join(file.name for file in uploads))
            try:
                validate_batch_size(len(uploads))
            except ValueError as exc:
                st.error(str(exc))
                uploads = []

        if st.button("Extract gas-sensing records", type="primary", key="synthex_gas_extract"):
            if not uploads:
                st.error("Upload at least one PDF.")
            else:
                records: list[SensorRecord] = []
                warnings: list[str] = []
                extractor = GeminiSensorExtractor(model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"))
                progress = st.progress(0, text="Starting gas-sensing extraction...")
                for index, uploaded in enumerate(uploads, start=1):
                    progress.progress((index - 1) / len(uploads), text=f"Extracting {index}/{len(uploads)} · {uploaded.name}")
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded.getbuffer())
                        tmp_path = tmp.name
                    try:
                        record, paper_warnings = extractor.extract_pdf(
                            tmp_path,
                            None if category == "Auto Detect" else category,
                            extraction_mode,
                        )
                        if not record.paper.title:
                            record.paper.title = uploaded.name
                        for sample in record.samples:
                            if not sample.source_paper_title:
                                sample.source_paper_title = record.paper.title
                        records.append(record)
                        warnings.extend(f"{uploaded.name}: {warning}" for warning in paper_warnings)
                    except Exception as exc:
                        warnings.append(f"{uploaded.name}: extraction failed — {exc}")
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                progress.progress(1.0, text="Gas-sensing extraction finished")
                if records:
                    st.session_state[_RECORD_KEY] = merge_records(records) if len(records) > 1 else records[0]
                    st.session_state[_WARNINGS_KEY] = warnings
                    st.success(f"Extracted {len(records)} of {len(uploads)} paper(s). Open Analytics & export to review the results.")
                else:
                    st.session_state[_WARNINGS_KEY] = warnings
                    st.error("No gas-sensing record was created. Review the extraction notes below.")

        st.divider()
        st.markdown("#### Discover gas-sensing papers")
        st.caption("Discovery results are navigation leads only; snippets never become scientific evidence.")
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            search_category = st.selectbox(
                "Search category",
                ["Metal Oxides", "Metal Sulfides", "Metal-Organic Frameworks", "Carbon-based", "Polymeric Nanomaterials", "Pure Metals / Alloys"],
                key="synthex_gas_search_category",
            )
        with c2:
            focus = st.text_input("Sensor focus", placeholder="e.g. NO2 chemiresistive", key="synthex_gas_search_focus")
        with c3:
            nres = st.number_input("Results", min_value=1, max_value=10, value=5, key="synthex_gas_search_n")
        if st.button("Search papers", key="synthex_gas_search"):
            try:
                found = search_papers(search_category, int(nres), focus or None)
                if not found:
                    st.info("No results returned.")
                for item in found:
                    title = item.get("title") or "Untitled paper"
                    url = item.get("url")
                    with st.container(border=True):
                        st.write(title)
                        if item.get("snippet"):
                            st.caption(item["snippet"])
                        if url:
                            st.link_button("Open paper", url)
            except Exception as exc:
                st.error(str(exc))

    with results:
        record = st.session_state.get(_RECORD_KEY)
        warnings = st.session_state.get(_WARNINGS_KEY) or []
        if warnings:
            with st.expander(f"Extraction / source-tracking notes ({len(warnings)})"):
                for warning in warnings:
                    st.warning(warning)

        if record is None:
            st.info("No gas-sensing extraction is loaded yet. Upload papers in the Extract papers tab.")
            return

        dep_methods = sorted({s.deposition.method for s in record.samples if s.deposition and s.deposition.method})
        targets = sorted({s.testing_conditions.target_analyte for s in record.samples if s.testing_conditions and s.testing_conditions.target_analyte})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Samples", len(record.samples))
        c2.metric("Deposition methods", len(dep_methods))
        c3.metric("Target analytes", len(targets))
        c4.metric("Source papers", len({s.source_paper_title for s in record.samples if s.source_paper_title}) or 1)

        overview, selectivity, response, analytics, export = st.tabs(
            ["Samples", "Selectivity", "Response time", "Visual analytics", "JSON / CSV"]
        )

        with overview:
            rows = []
            for i, sample in enumerate(record.samples, start=1):
                performance = sample.performance
                conditions = sample.testing_conditions
                deposition = sample.deposition
                rows.append({
                    "paper": sample.source_paper_title,
                    "sample": sample.sample_id or f"Sample {i}",
                    "material": sample.material,
                    "sensor_type": sample.sensor_type,
                    "target": conditions.target_analyte if conditions else None,
                    "deposition": (deposition.method_variant or deposition.method) if deposition else None,
                    "response_time": performance.response_time.value.raw_value if performance and performance.response_time and performance.response_time.value else None,
                    "recovery_time": performance.recovery_time.value.raw_value if performance and performance.recovery_time and performance.recovery_time.value else None,
                    "LOD": performance.limit_of_detection.value.raw_value if performance and performance.limit_of_detection and performance.limit_of_detection.value else None,
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        with selectivity:
            matrix = selectivity_matrix(record)
            if matrix.empty:
                st.info("No exact numeric selectivity ratios are available. Qualitative and inequality evidence remains in the structured record.")
            else:
                st.dataframe(matrix, width="stretch")
                fig = plot_selectivity_heatmap(record)
                st.pyplot(fig, use_container_width=True)
                st.download_button("Download heat map PNG", figure_to_png_bytes(fig), "synthex_selectivity_heatmap.png", "image/png")
            st.markdown("#### Reported selectivity evidence")
            for i, sample in enumerate(record.samples, start=1):
                selection = sample.performance.selectivity if sample.performance and sample.performance.selectivity else None
                if not selection:
                    continue
                st.write(f"**{sample.sample_id or sample.material or f'Sample {i}'}** — target: {selection.target_analyte or 'not specified'}")
                if selection.qualitative_statement:
                    st.write(selection.qualitative_statement)
                for entry in selection.entries:
                    st.write({
                        "interferent": entry.interferent,
                        "raw_ratio": entry.raw_ratio,
                        "numeric_ratio": entry.selectivity_ratio,
                        "target_response": entry.target_response,
                        "interferent_response": entry.interferent_response,
                    })

        with response:
            frame = response_time_points(record)
            if frame.empty:
                st.info("No response-time values extracted.")
            else:
                st.dataframe(frame, width="stretch", hide_index=True)
                groups = response_time_groups(record)
                if groups:
                    chosen = st.selectbox("Contour group", list(groups.keys()), key="synthex_gas_contour_group")
                    fig = plot_response_time_contour(record, chosen)
                    if fig:
                        st.pyplot(fig, use_container_width=True)
                        st.download_button("Download contour PNG", figure_to_png_bytes(fig), "synthex_response_time_contour.png", "image/png")
                else:
                    st.info("No defensible contour group yet. A contour needs enough like-for-like observations across temperature and concentration.")

        with analytics:
            a, b = st.columns(2)
            with a:
                st.markdown("#### Selectivity heat map")
                fig = plot_selectivity_heatmap(record)
                if fig:
                    st.pyplot(fig, use_container_width=True)
                else:
                    st.info("Need numeric selectivity comparisons.")
            with b:
                st.markdown("#### Radar comparison")
                groups = radar_groups(record)
                if groups:
                    choice = st.selectbox("Radar comparison group", list(groups.keys()), key="synthex_gas_radar_group")
                    fig = plot_radar(record, choice)
                    st.pyplot(fig, use_container_width=True)
                    st.caption("Only like-for-like target analyte and sensor-type groups are compared; values are normalized within the selected group.")
                else:
                    st.info("No like-for-like radar group yet.")

        with export:
            st.json(record.model_dump(mode="json"))
            with st.container(horizontal=True):
                st.download_button("Download structured JSON", to_json_bytes(record), "synthex_sensor_record.json", "application/json")
                flat = flatten_record(record)
                st.download_button("Download flattened CSV", flat.to_csv(index=False).encode("utf-8"), "synthex_sensor_record.csv", "text/csv")
