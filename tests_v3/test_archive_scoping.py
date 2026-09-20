from __future__ import annotations

from pathlib import Path
import json

from streamlit.testing.v1 import AppTest

from synthex_platform.archive_scoping import (
    ArchiveQueryContext,
    DataScope,
    SCOPE_LABELS,
    THESIS_DOMAINS,
    UNKNOWN_LEGACY_DOMAIN,
    VISUAL_SCOPE_STATE_KEY,
    archive_domain,
    begin_extraction_action,
    current_extraction_from_state,
    domain_archive_summaries,
    record_current_extraction,
    select_archives,
)
from synthex_platform.batch import combined_result_rows
from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.models import Evidence, ExperimentRecord, MaterialEntity, Measurement, SourceRecord
from synthex_platform.visual.analytics.projection import project_archives
from synthex_platform.visual.analytics.specs import build_visualization_spec


def _archive(index: int, domain: str | None, property_name: str, *, source_id: str | None = None) -> SynthexArchive:
    source_id = source_id or f"src-{index}"
    material_id = f"mat-{index}"
    evidence = Evidence(source_id=source_id, page=1, source_type="text", text_snippet=f"{index}.0 u")
    return SynthexArchive(
        metadata=ArchiveMetadata(archive_id=f"arc-{index}", domain=domain),
        sources=[SourceRecord(source_id=source_id, title=f"Paper {index}", year=2020 + index)],
        materials=[MaterialEntity(material_id=material_id, name=f"Material {index}")],
        experiments=[ExperimentRecord(
            experiment_id=f"exp-{index}",
            experiment_type="measurement",
            material_ids=[material_id],
            conditions=[Measurement(property="temperature", value=float(20 + index), unit="°C")],
            outputs=[Measurement(
                property=property_name,
                value=float(index),
                unit="u",
                evidence=[evidence],
            )],
        )],
    )


def test_current_extraction_isolates_new_catalysis_from_old_battery_archive():
    battery = _archive(1, "batteries", "specific_capacity")
    catalysis = _archive(2, "catalysis", "turnover_frequency")
    state: dict = {}
    current = record_current_extraction(state, [catalysis], run_id="run-cat")
    selected = select_archives(
        [battery, catalysis],
        ArchiveQueryContext(scope=DataScope.CURRENT_EXTRACTION, run_id="run-cat"),
        current_extraction=current,
    )
    assert [item.metadata.archive_id for item in selected] == ["arc-2"]


def test_current_domain_isolation_is_explicit():
    archives = [_archive(1, "batteries", "capacity"), _archive(2, "corrosion", "corrosion_rate")]
    selected = select_archives(
        archives,
        ArchiveQueryContext(scope=DataScope.CURRENT_DOMAIN, domain="corrosion"),
    )
    assert [archive_domain(item) for item in selected] == ["corrosion"]


def test_selected_archived_papers_are_source_isolated():
    archives = [_archive(1, "corrosion", "rate"), _archive(2, "corrosion", "rate")]
    selected = select_archives(
        archives,
        ArchiveQueryContext(scope=DataScope.SELECTED_SOURCES, source_ids={"src-2"}),
    )
    assert [item.metadata.archive_id for item in selected] == ["arc-2"]


def test_batch_current_extraction_tracks_every_successful_archive_and_source():
    state: dict = {}
    record = record_current_extraction(
        state,
        [_archive(1, "batteries", "capacity"), _archive(2, "batteries", "voltage")],
        run_id="batch-1",
        completed_at="2026-01-01T00:00:00+00:00",
    )
    assert record is not None
    assert record.archive_ids == ("arc-1", "arc-2")
    assert record.source_ids == ("src-1", "src-2")
    assert record.domains == ("batteries",)


def test_successful_new_action_replaces_previous_current_identity():
    state: dict = {}
    record_current_extraction(state, [_archive(1, "batteries", "capacity")], run_id="first")
    record_current_extraction(state, [_archive(2, "catalysis", "activity")], run_id="second")
    current = current_extraction_from_state(state)
    assert current and current.run_id == "second" and current.archive_ids == ("arc-2",)


def test_failed_action_clears_identity_and_defaults_visual_scope_without_fallback():
    state: dict = {}
    record_current_extraction(state, [_archive(1, "batteries", "capacity")], run_id="first")
    begin_extraction_action(state)
    assert current_extraction_from_state(state) is None
    assert state[VISUAL_SCOPE_STATE_KEY] == SCOPE_LABELS[DataScope.CURRENT_EXTRACTION]
    assert select_archives(
        [_archive(1, "batteries", "capacity")],
        ArchiveQueryContext(scope=DataScope.CURRENT_EXTRACTION),
        current_extraction=None,
    ) == []


def test_property_discovery_uses_only_scoped_archives():
    battery = _archive(1, "batteries", "specific_capacity")
    catalysis = _archive(2, "catalysis", "turnover_frequency")
    scoped = select_archives(
        [battery, catalysis],
        ArchiveQueryContext(scope=DataScope.CURRENT_DOMAIN, domain="catalysis"),
    )
    assert {row.property_name for row in project_archives(scoped)} == {"turnover_frequency"}


def test_domain_catalog_keeps_all_ten_thesis_domains_when_empty():
    summaries = domain_archive_summaries([])
    expected = {slug for slug, _ in THESIS_DOMAINS}
    assert expected <= {item["domain"] for item in summaries}
    assert all(item["archive_count"] == 0 for item in summaries)


def test_missing_domain_is_unknown_legacy_without_filename_guessing():
    archive = _archive(1, None, "specific_capacity")
    archive.sources[0].title = "Obviously a battery paper.pdf"
    assert archive_domain(archive) == UNKNOWN_LEGACY_DOMAIN


def test_custom_cross_domain_combination_does_not_mutate_and_is_not_chart_eligible():
    battery = _archive(1, "batteries", "shared_metric")
    catalysis = _archive(2, "catalysis", "shared_metric")
    original = [battery.model_dump(), catalysis.model_dump()]
    selected = select_archives(
        [battery, catalysis],
        ArchiveQueryContext(scope=DataScope.CUSTOM_COMBINATION, archive_ids={"arc-1", "arc-2"}),
    )
    rows = project_archives(selected)
    spec = build_visualization_spec(rows, "scatter", x_field="conditions.temperature", y_field="value")
    assert not spec.eligible and spec.reason == "incompatible_cross_domain_records"
    assert [battery.model_dump(), catalysis.model_dump()] == original


def test_empty_selected_and_custom_scopes_never_expand_to_entire_archive():
    archives = [_archive(1, "batteries", "capacity")]
    assert select_archives(archives, ArchiveQueryContext(scope=DataScope.SELECTED_SOURCES)) == []
    assert select_archives(archives, ArchiveQueryContext(scope=DataScope.CUSTOM_COMBINATION)) == []


def test_archive_explorer_rows_remain_domain_isolated():
    archives = [_archive(1, "batteries", "capacity"), _archive(2, "corrosion", "corrosion_rate")]
    scoped = select_archives(
        archives,
        ArchiveQueryContext(scope=DataScope.CURRENT_DOMAIN, domain="corrosion"),
    )
    rows = combined_result_rows(scoped)
    assert rows and {row["domain"] for row in rows} == {"corrosion"}


def test_streamlit_visualize_defaults_to_current_catalysis_run_not_older_battery_data():
    battery = _archive(1, "batteries", "specific_capacity")
    catalysis = _archive(2, "catalysis", "turnover_frequency")
    state: dict = {}
    record_current_extraction(
        state,
        [catalysis],
        run_id="run-catalysis",
        completed_at="2026-01-01T00:00:00+00:00",
    )
    app = AppTest.from_file(Path(__file__).parents[1] / "platform_app.py", default_timeout=25)
    app.session_state["synthex_batch_archives"] = [
        battery.model_dump(mode="json", exclude_none=True),
        catalysis.model_dump(mode="json", exclude_none=True),
    ]
    app.session_state["synthex_current_extraction"] = state["synthex_current_extraction"]
    app.session_state[VISUAL_SCOPE_STATE_KEY] = SCOPE_LABELS[DataScope.CURRENT_EXTRACTION]
    app.run()
    app.sidebar.radio[0].set_value("Visualize Data").run()

    assert not app.exception
    data_scope = next(widget for widget in app.selectbox if widget.label == "Data scope")
    prop = next(widget for widget in app.selectbox if widget.label == "Property")
    assert data_scope.value == "Current extraction"
    assert prop.options == ["turnover_frequency"]
    assert not any("specific_capacity" in str(frame.value) for frame in app.dataframe)

    data_scope.set_value("Entire selected domain").run()
    domain = next(widget for widget in app.selectbox if widget.label == "Domain")
    assert domain.value == "catalysis"
    domain_properties = next(widget for widget in app.selectbox if widget.label == "Property").options
    assert "turnover_frequency" in domain_properties
    assert "specific_capacity" not in domain_properties

    app.sidebar.radio[0].set_value("Explore Results").run()
    archive_domain_widget = next(widget for widget in app.selectbox if widget.label == "Archive domain")
    assert archive_domain_widget.value == "catalysis"
    catalysis_scope = next(widget for widget in app.selectbox if widget.label == "Result scope")
    assert any("Paper 2" in option for option in catalysis_scope.options)
    assert not any("Paper 1" in option for option in catalysis_scope.options)

    archive_domain_widget.set_value("batteries").run()
    battery_scope = next(widget for widget in app.selectbox if widget.label == "Result scope")
    assert any("Paper 1" in option for option in battery_scope.options)
    assert not any("Paper 2" in option for option in battery_scope.options)


def test_streamlit_scope_switching_makes_cross_domain_selection_deliberate():
    battery = _archive(1, "batteries", "specific_capacity")
    catalysis = _archive(2, "catalysis", "turnover_frequency")
    state: dict = {}
    current = record_current_extraction(
        state,
        [catalysis],
        run_id="run-catalysis",
        completed_at="2026-01-01T00:00:00+00:00",
    )
    archive_payloads = json.dumps([
        battery.model_dump(mode="json", exclude_none=True),
        catalysis.model_dump(mode="json", exclude_none=True),
    ])
    current_payload = json.dumps(current.model_dump(mode="json"))
    source = f'''\
import json
from synthex_platform.archive_scoping import CurrentExtraction
from synthex_platform.core.archive import SynthexArchive
from synthex_platform.visual.analytics.streamlit_panel import render_visual_explorer

archives = [SynthexArchive.model_validate(item) for item in json.loads({archive_payloads!r})]
current = CurrentExtraction.model_validate(json.loads({current_payload!r}))
render_visual_explorer(
    archives,
    current_extraction=current,
    saved_archives=archives,
    current_domain="catalysis",
)
'''
    app = AppTest.from_string(source, default_timeout=25).run()
    assert next(widget for widget in app.selectbox if widget.label == "Property").options == ["turnover_frequency"]

    scope = next(widget for widget in app.selectbox if widget.label == "Data scope")
    scope.set_value("Selected archived papers").run()
    domains = next(widget for widget in app.multiselect if widget.label == "Archived-paper domains")
    domains.set_value(["catalysis", "batteries"]).run()
    papers = next(widget for widget in app.multiselect if widget.label == "Archived papers")
    papers.set_value(["arc-1", "arc-2"]).run()
    assert any("spans multiple domains" in warning.value for warning in app.warning)

    next(widget for widget in app.selectbox if widget.label == "Data scope").set_value("Current extraction").run()
    assert next(widget for widget in app.selectbox if widget.label == "Property").options == ["turnover_frequency"]
    assert not any("spans multiple domains" in warning.value for warning in app.warning)
