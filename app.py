from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from search import search_papers
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

st.set_page_config(page_title='Synthex V2.1', page_icon='🧪', layout='wide')
st.markdown('''
<style>
.block-container {padding-top: 1.2rem; max-width: 1550px;}
.hero {padding: 1.25rem 1.45rem; border:1px solid rgba(128,128,128,.25); border-radius:18px; margin-bottom:1rem;}
.hero h1 {margin:0; font-size:2.25rem;}
.hero p {margin:.35rem 0 0; opacity:.74;}
.note {font-size:.9rem; opacity:.75;}
</style>
<div class='hero'><h1>🧪 Synthex V2.1</h1><p>Nanomaterial synthesis → deposition → sensor performance → evidence-backed visual analytics.</p></div>
''', unsafe_allow_html=True)

if 'record' not in st.session_state:
    st.session_state.record = None
if 'warnings' not in st.session_state:
    st.session_state.warnings = []

with st.sidebar:
    st.header('Extraction setup')
    extraction_mode = st.selectbox('Extraction mode', ['Full Sensor Record', 'Synthesis + Deposition', 'Sensor Performance'])
    category = st.selectbox('Material category', ['Auto Detect', 'Metal Oxides', 'Metal Sulfides', 'Metal-Organic Frameworks', 'Carbon-based', 'Polymeric Nanomaterials', 'Pure Metals / Alloys'])
    model = st.text_input('Gemini model', value=os.getenv('GEMINI_MODEL', 'gemini-3.8-flash'))
    uploads = st.file_uploader('Upload one or more research PDFs', type=['pdf'], accept_multiple_files=True)
    run = st.button('Extract with Gemini', type='primary', use_container_width=True)

    st.divider()
    st.subheader('Offline benchmark')
    if st.button('Load real-paper replay fixtures', use_container_width=True):
        p = Path(__file__).parent / 'benchmark' / 'expected_records.json'
        raw = json.loads(p.read_text(encoding='utf-8'))
        records = [SensorRecord.model_validate(x) for x in raw]
        st.session_state.record = merge_records(records)
        st.session_state.warnings = ['Replay fixtures are literature-derived expected values, not live Gemini outputs.']
        st.rerun()

    if st.button('Clear', use_container_width=True):
        st.session_state.record = None
        st.session_state.warnings = []
        st.rerun()

    st.caption('Secrets are read from .env. The UI never displays GEMINI_API_KEY or SERPER_API_KEY.')

if run:
    if not uploads:
        st.error('Upload at least one PDF.')
    else:
        records, warnings = [], []
        extractor = GeminiSensorExtractor(model=model)
        progress = st.progress(0, text='Starting extraction…')
        for idx, uploaded in enumerate(uploads, start=1):
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                tmp.write(uploaded.getbuffer())
                tmp_path = tmp.name
            try:
                progress.progress((idx-1)/len(uploads), text=f'Extracting {uploaded.name}…')
                record, w = extractor.extract_pdf(
                    tmp_path,
                    None if category == 'Auto Detect' else category,
                    extraction_mode,
                )
                if not record.paper.title:
                    record.paper.title = uploaded.name
                for s in record.samples:
                    if not s.source_paper_title:
                        s.source_paper_title = record.paper.title
                records.append(record)
                warnings.extend([f'{uploaded.name}: {x}' for x in w])
            finally:
                try: os.unlink(tmp_path)
                except OSError: pass
        st.session_state.record = merge_records(records) if len(records) > 1 else records[0]
        st.session_state.warnings = warnings
        progress.progress(1.0, text='Extraction complete')

record = st.session_state.record

main_tab, search_tab = st.tabs(['Extraction & analytics', 'Search papers online'])

with search_tab:
    st.subheader('Search papers')
    c1, c2, c3 = st.columns([2,2,1])
    with c1:
        search_category = st.selectbox('Search category', ['Metal Oxides','Metal Sulfides','Metal-Organic Frameworks','Carbon-based','Polymeric Nanomaterials','Pure Metals / Alloys'], key='search_category')
    with c2:
        focus = st.text_input('Sensor focus', placeholder='e.g. NO2 chemiresistive, glucose biosensor')
    with c3:
        nres = st.number_input('Results', min_value=1, max_value=10, value=5)
    if st.button('Search with Serper'):
        try:
            results = search_papers(search_category, int(nres), focus or None)
            if not results:
                st.info('No results returned.')
            for item in results:
                st.markdown(f"### [{item.get('title')}]({item.get('url')})")
                if item.get('snippet'): st.write(item['snippet'])
        except Exception as exc:
            st.error(str(exc))

with main_tab:
    if record is None:
        st.info('Upload papers and extract, or load the offline real-paper replay benchmark from the sidebar.')
        st.stop()

    if st.session_state.warnings:
        with st.expander(f'Validation / provenance notes ({len(st.session_state.warnings)})'):
            for w in st.session_state.warnings:
                st.warning(w)

    dep_methods = sorted({s.deposition.method for s in record.samples if s.deposition and s.deposition.method})
    targets = sorted({s.testing_conditions.target_analyte for s in record.samples if s.testing_conditions and s.testing_conditions.target_analyte})
    c1,c2,c3,c4 = st.columns(4)
    c1.metric('Samples', len(record.samples))
    c2.metric('Deposition methods', len(dep_methods))
    c3.metric('Target analytes', len(targets))
    c4.metric('Source papers', len({s.source_paper_title for s in record.samples if s.source_paper_title}) or 1)

    overview, selectivity, response, analytics, export = st.tabs(['Samples', 'Selectivity', 'Response time', 'Visual analytics', 'JSON / CSV'])

    with overview:
        rows = []
        for i,s in enumerate(record.samples, start=1):
            p=s.performance; tc=s.testing_conditions; d=s.deposition
            rows.append({
                'paper': s.source_paper_title,
                'sample': s.sample_id or f'Sample {i}',
                'material': s.material,
                'sensor_type': s.sensor_type,
                'target': tc.target_analyte if tc else None,
                'deposition': (d.method_variant or d.method) if d else None,
                'response_time': p.response_time.value.raw_value if p and p.response_time and p.response_time.value else None,
                'recovery_time': p.recovery_time.value.raw_value if p and p.recovery_time and p.recovery_time.value else None,
                'LOD': p.limit_of_detection.value.raw_value if p and p.limit_of_detection and p.limit_of_detection.value else None,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with selectivity:
        matrix = selectivity_matrix(record)
        if matrix.empty:
            st.info('No exact numeric selectivity ratios are available. Qualitative selectivity and inequality values are retained in JSON.')
        else:
            st.dataframe(matrix, use_container_width=True)
            fig = plot_selectivity_heatmap(record)
            st.pyplot(fig, use_container_width=True)
            st.download_button('Download heat map PNG', figure_to_png_bytes(fig), 'synthex_selectivity_heatmap.png', 'image/png')
        st.markdown('#### Reported selectivity evidence')
        for i,s in enumerate(record.samples, start=1):
            sel=s.performance.selectivity if s.performance and s.performance.selectivity else None
            if not sel: continue
            st.write(f"**{s.sample_id or s.material or f'Sample {i}'}** — target: {sel.target_analyte or 'not specified'}")
            if sel.qualitative_statement: st.write(sel.qualitative_statement)
            for e in sel.entries:
                st.write({'interferent': e.interferent, 'raw_ratio': e.raw_ratio, 'numeric_ratio': e.selectivity_ratio, 'target_response': e.target_response, 'interferent_response': e.interferent_response})

    with response:
        df = response_time_points(record)
        if df.empty:
            st.info('No response-time values extracted.')
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
            groups = response_time_groups(record)
            if groups:
                chosen = st.selectbox('Contour group', list(groups.keys()))
                fig = plot_response_time_contour(record, chosen)
                if fig:
                    st.pyplot(fig, use_container_width=True)
                    st.download_button('Download contour PNG', figure_to_png_bytes(fig), 'synthex_response_time_contour.png', 'image/png')
            else:
                st.info('No defensible contour group yet. A contour requires ≥4 observations for the same material + target + sensor type, spanning ≥2 temperatures and ≥2 concentrations.')

    with analytics:
        a,b = st.columns(2)
        with a:
            st.markdown('#### Selectivity heat map')
            fig=plot_selectivity_heatmap(record)
            if fig: st.pyplot(fig, use_container_width=True)
            else: st.info('Need numeric selectivity comparisons.')
        with b:
            st.markdown('#### Radar comparison')
            rg = radar_groups(record)
            if rg:
                rg_choice = st.selectbox('Radar comparison group', list(rg.keys()))
                fig=plot_radar(record, rg_choice)
                st.pyplot(fig, use_container_width=True)
                st.caption('Only samples with the same target analyte and sensor type are grouped. Values are normalized within that group.')
            else:
                st.info('No like-for-like radar group yet. Need at least two samples with the same target + sensor type and ≥3 usable performance dimensions each.')

    with export:
        st.json(record.model_dump(mode='json'))
        st.download_button('Download structured JSON', to_json_bytes(record), 'synthex_sensor_record.json', 'application/json')
        df = flatten_record(record)
        st.download_button('Download flattened CSV', df.to_csv(index=False).encode('utf-8'), 'synthex_sensor_record.csv', 'text/csv')
