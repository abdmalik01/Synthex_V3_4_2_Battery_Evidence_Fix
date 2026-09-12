import json
from copy import deepcopy
from pathlib import Path

from benchmark_battery_material import GOLD_PATH, OUTPUT_DIR, _norm_unit, console_report_json, evaluate
from synthex_platform.core.archive import ArchiveMetadata
from synthex_platform.extraction.battery_evidence import verify_battery_evidence
from synthex_platform.extraction.battery_models import BatteryDocument
from synthex_v2.pdf_utils_v2 import extract_pages, pages_to_marked_text


ROOT = Path(__file__).parents[1]
GOLD_DOCUMENT_PATH = ROOT / "benchmark" / "batteries_v1" / "batteries_11_00142_gold_document.json"
PAPER_PATH = ROOT / "benchmark" / "batteries_v1" / "corpus_pdfs" / "batteries-11-00142.pdf"


def _gold_document() -> BatteryDocument:
    document = BatteryDocument.model_validate(json.loads(GOLD_DOCUMENT_PATH.read_text(encoding="utf-8")))
    source_text = pages_to_marked_text(extract_pages(PAPER_PATH))
    return verify_battery_evidence(document, source_text)


def test_gold_document_passes_strict_value_condition_and_provenance_metrics():
    report = evaluate(_gold_document())
    assert report["value_accuracy"] == 1.0
    assert report["condition_association_accuracy"] == 1.0
    assert report["provenance_coverage"] == 1.0
    assert report["overall_score"] == 1.0
    assert all(check["pass"] for check in report["performance_checks"])


def test_value_on_wrong_sample_variant_does_not_pass_strict_performance_check():
    raw = json.loads(GOLD_DOCUMENT_PATH.read_text(encoding="utf-8"))
    changed = deepcopy(raw)
    group = next(g for g in changed["battery_groups"] if "700" in g["variant_label"])
    group["variant_label"] = "600 C"
    group["calcination_temperature"] = "600 C"
    doc = BatteryDocument.model_validate(changed)

    report = evaluate(doc)

    assert report["value_accuracy"] == 1.0
    assert report["condition_association_accuracy"] < 1.0
    assert not all(check["pass"] for check in report["performance_checks"])


def test_forced_c_rate_on_conflicted_retention_is_not_counted_as_resolved():
    doc = _gold_document()
    group = next(g for g in doc.battery_groups if "700" in g.variant_label)
    retention = next(p for p in group.performance_points if p.property == "capacity_retention")
    retention.c_rate = "1 C"

    report = evaluate(doc)
    check = next(c for c in report["performance_checks"] if c["property"] == "capacity_retention")

    assert check["value_pass"]
    assert not check["conditions_pass"]
    assert check["c_rate_status"] == "conflicted"


def test_missing_evidence_reduces_provenance_without_losing_value_credit():
    doc = _gold_document()
    group = next(g for g in doc.battery_groups if "700" in g.variant_label)
    group.performance_points[0].evidence = []

    report = evaluate(doc)

    assert report["value_accuracy"] == 1.0
    assert report["provenance_coverage"] < 1.0
    assert not report["performance_checks"][0]["pass"]


def test_fraction_and_weight_percent_are_compared_scientifically():
    doc = _gold_document()
    fabrication = doc.shared_protocols[0].electrode_fabrication
    fabrication.active_material_fraction.value = 0.8
    fabrication.active_material_fraction.unit = "fraction"

    report = evaluate(doc)
    check = next(c for c in report["checks"] if c["check"] == "80 wt% active material")
    assert check["pass"]


def test_unicode_resistance_symbols_match_ohm_unit():
    assert _norm_unit("Ω") == "ohm"
    assert _norm_unit("Ω") == "ohm"
    assert _norm_unit("Ohm") == "ohm"


def test_benchmark_paths_are_anchored_to_repository():
    assert GOLD_PATH == ROOT / "benchmark" / "batteries_v1" / "batteries_11_00142_gold.json"
    assert OUTPUT_DIR == ROOT / "benchmark" / "outputs"
    assert GOLD_PATH.is_absolute()
    assert OUTPUT_DIR.is_absolute()


def test_console_report_is_safe_for_legacy_windows_encodings():
    rendered = console_report_json({"unit": "Ω", "temperature": "700 °C"})
    rendered.encode("cp1252")
    assert "\\u2126" in rendered


def test_runtime_archive_metadata_uses_central_software_version():
    from synthex_platform import __version__

    metadata = ArchiveMetadata(archive_id="arc-test")
    assert metadata.software_version == __version__
    assert metadata.schema_version == "3.4.0"
    assert metadata.generator == f"Synthex V{__version__}"
