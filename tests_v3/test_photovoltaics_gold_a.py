from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf

from benchmark.photovoltaics_v1.recover_gold_a import recover_gold_a
from benchmark.photovoltaics_v1.score_gold_a import score_gold_a
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.visual.analytics.projection import project_archives


CASE_DIR = Path(__file__).parents[1] / "benchmark" / "photovoltaics_v1"


def _read(name: str) -> dict:
    return json.loads((CASE_DIR / name).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pv_gold_a_source_and_gold_were_locked_before_any_provider_call():
    lock = _read("source_lock.json")
    assert lock["case_id"] == "PV-GOLD-A"
    assert lock["locked_before_provider_call"] is True
    assert lock["provider_calls_at_lock"] == 0
    assert lock["source_origin"] == "official_publisher_open_access_pdf"
    assert _sha256(CASE_DIR / lock["source_file"]) == lock["source_sha256"]
    assert _sha256(CASE_DIR / lock["gold_file"]) == lock["gold_sha256"]


def test_pv_gold_a_offline_recovery_scores_all_four_device_variants():
    gold = _read("gold_a.json")
    archive, recovered = recover_gold_a()
    score = score_gold_a(archive, gold)
    assert recovered == gold["rows"]
    assert score["passed"] == score["total"] == 4
    assert score["devices"] == 4
    assert score["experiments"] == 4
    assert score["outputs"] == 20
    assert score["analytics_rows"] == 20
    assert score["scientific_safety"] == {
        "analytics_preserve_device_and_context": True,
        "active_area_not_inferred": True,
        "percent_properties_preserved": True,
        "property_identity_preserved": True,
        "quarantine_count": 0,
    }


def test_pv_gold_a_archive_preserves_ordered_stack_device_links_and_exact_conditions():
    archive, _ = recover_gold_a()
    assert len(archive.devices) == 4
    assert all(len(device.configuration["layer_stack"]) == 6 for device in archive.devices)
    assert all(
        [layer["sequence_index"] for layer in device.configuration["layer_stack"]] == list(range(6))
        for device in archive.devices
    )
    assert all(experiment.device_id in {device.device_id for device in archive.devices} for experiment in archive.experiments)
    assert all(experiment.device_ids == [experiment.device_id] for experiment in archive.experiments)
    assert sum(len(experiment.outputs) for experiment in archive.experiments) == 20
    for experiment in archive.experiments:
        for output in experiment.outputs:
            assert output.conditions["illumination_spectrum"] == "AM 1.5 G"
            assert output.conditions["irradiance"] == 100.0
            assert output.conditions["irradiance_unit"] == "mW/cm2"
            assert output.conditions["active_area"] == "not reported"
            assert output.conditions["scan_direction"] == "not reported"
            assert output.evidence[0].page == 8
            assert output.raw_value in output.evidence[0].text_snippet


def test_pv_gold_a_analytics_keep_device_architecture_and_do_not_infer_area():
    archive, _ = recover_gold_a()
    rows = project_archives([archive])
    assert len(rows) == 20
    assert all(row.device_id for row in rows)
    assert all(len(row.conditions["device_layer_stack"]) == 6 for row in rows)
    assert all(row.conditions["active_area"] == "not reported" for row in rows)
    treated = [row for row in rows if row.conditions["device_variant"] != "bare"]
    assert all(row.conditions["device_process_processing_time"] in {5.0, 10.0, 15.0} for row in treated)


def test_official_pv_gold_a_source_routes_to_photovoltaics():
    lock = _read("source_lock.json")
    with pymupdf.open(CASE_DIR / lock["source_file"]) as document:
        text = "\n".join(page.get_text() for page in document)
    route = DomainRouter().route_text(text)
    assert route.domain == "photovoltaics"
    assert "photovoltaic_performance" in route.paper_types
    assert "device_fabrication" in route.paper_types
