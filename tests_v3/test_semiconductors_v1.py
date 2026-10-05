from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.semiconductors_v1.interim_audit import run_interim_audit
from benchmark.semiconductors_v1.recover_cases import recover_all_cases
from benchmark.semiconductors_v1.source_tables import ROOT, source_lock
from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.export.analytics_projection import project_results_rows
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.semiconductors_contract import _unit_key, semiconductor_admission_decision


@pytest.fixture(scope="module")
def archives():
    return recover_all_cases()


@pytest.fixture(scope="module")
def audit():
    return run_interim_audit()


def _outputs(archive):
    return [output for experiment in archive.experiments for output in experiment.outputs]


def test_four_pdf_and_gold_locks_are_present_and_exact():
    for case in ("SEM-GOLD-A", "SEM-TRANSPORT-B", "SEM-OPTICAL-C", "SEM-PROCESS-D"):
        lock = source_lock(case)
        gold = json.loads((ROOT / lock["gold_file"]).read_text(encoding="utf-8"))
        assert lock["case_id"] == gold["case_id"] == case
        assert lock["doi"] == gold["source"]["doi"]
        assert lock["status"] == "gold_locked_before_recovery_and_provider_call"


def test_source_table_parity_and_offline_counts(audit, archives):
    assert all(audit["source_gold_parity"].values())
    assert {case: len(_outputs(archive)) for case, archive in archives.items()} == {
        "SEM-GOLD-A": 20, "SEM-TRANSPORT-B": 46,
        "SEM-OPTICAL-C": 13, "SEM-PROCESS-D": 20,
    }
    assert all(not archive.domain_payloads[0].values["admissibility"]["quarantined_objects"] for archive in archives.values())


def test_gold_a_keeps_scaled_units_and_ga_separate_from_carriers(archives):
    archive = archives["SEM-GOLD-A"]
    outputs = _outputs(archive)
    assert len(archive.devices) == len(archive.experiments) == 4
    assert {output.property for output in outputs} == {
        "carrier_concentration", "hall_mobility", "resistivity",
        "sheet_resistance", "optical_band_gap",
    }
    assert sorted(output.normalized_value for output in outputs if output.property == "carrier_concentration") == pytest.approx([
        1.36e20, 2.96e20, 4.23e20, 6.55e20,
    ])
    assert all(output.method == "Hall_effect" for output in outputs if output.property == "hall_mobility")
    assert all("measurement_temperature" not in output.conditions for output in outputs)
    assert {item.dopants[0]["nominal_atomic_percent"] for item in archive.materials if item.dopants} == {1.0, 5.0, 8.0}


def test_transport_b_missing_cells_and_process_state_do_not_leak(archives):
    archive = archives["SEM-TRANSPORT-B"]
    outputs = _outputs(archive)
    assert len(archive.devices) == 20 and len(outputs) == 46
    assert sum(output.property == "resistivity" for output in outputs) == 20
    assert sum(output.property == "carrier_concentration" for output in outputs) == 13
    assert sum(output.property == "carrier_mobility" for output in outputs) == 13
    assert all(output.conditions["measurement_temperature"] == "room_temperature" for output in outputs)
    assert all(any(parameter.property == "annealing_temperature" for parameter in process.parameters)
               for process in archive.processes if "annealed" in process.name)
    assert all("measurement_temperature" not in parameter.conditions for process in archive.processes for parameter in process.parameters)


def test_optical_c_preserves_substrate_and_derivation(archives):
    archive = archives["SEM-OPTICAL-C"]
    outputs = _outputs(archive)
    gap = [item for item in outputs if item.property == "optical_band_gap"]
    pl = [item for item in outputs if item.property == "photoluminescence_peak"]
    assert len(gap) == 5 and len(pl) == 8
    assert all(item.conditions["substrate"] == "sapphire" and item.conditions["apparent"] is True for item in gap)
    assert {item.conditions["substrate"] for item in pl} == {"Si(100)", "Si(111)"}
    assert {item.conditions["measurement_temperature"] for item in pl} == {11, 300}
    assert len(archive.devices) == 9  # five sapphire, four distinct Si films
    assert {tuple(sorted(material.composition.items())) for material in archive.materials if material.composition} >= {
        (("Al", 0.12), ("In", 0.88)), (("Al", 0.16), ("In", 0.84)),
    }


def test_process_d_keeps_two_series_and_hall_scale(archives):
    archive = archives["SEM-PROCESS-D"]
    outputs = _outputs(archive)
    assert len(archive.devices) == len(archive.processes) == 10 and len(outputs) == 20
    assert sum(item.conditions["processing_series"] == "temperature_at_220_s" for item in outputs) == 10
    assert sum(item.conditions["processing_series"] == "time_at_700_c" for item in outputs) == 10
    assert sum(process.name == "APCVD and FTO tempering" for process in archive.processes) == 10
    hall = [item for item in outputs if item.property == "hall_coefficient"]
    assert all(item.value < 0 and item.normalized_value == pytest.approx(item.value * 1e-2) for item in hall)
    assert all(item.conditions["measurement_temperature"] == 300 for item in hall)


def test_semiconductor_contract_rejects_unsupported_evidence_units_and_missing_values(archives):
    source = _outputs(archives["SEM-GOLD-A"])[0]
    no_page = source.model_copy(deep=True)
    no_page.evidence[0].page = None
    assert not semiconductor_admission_decision(no_page, role="result").admitted
    caption = source.model_copy(deep=True)
    caption.evidence = [Evidence(page=4, source_type=SourceType.figure_caption,
                                 original_source_type="figure_caption", verbatim_match=True,
                                 text_snippet=source.raw_value, locator="figure=4;caption")]
    assert not semiconductor_admission_decision(caption, role="result").admitted
    missing = source.model_copy(deep=True)
    missing.raw_value = "N/A"
    assert not semiconductor_admission_decision(missing, role="result").admitted
    wrong_unit = source.model_copy(deep=True)
    wrong_unit.unit = "S/cm"
    assert not semiconductor_admission_decision(wrong_unit, role="result").admitted
    calculated = source.model_copy(deep=True)
    calculated.conditions["scientific_type"] = "calculated"
    assert not semiconductor_admission_decision(calculated, role="result", modality="experimental").admitted


def test_breakdown_field_mega_and_milli_prefixes_are_distinct():
    assert _unit_key("MV/cm") == "megav/cm"
    assert _unit_key("mV/cm") == "mv/cm"
    assert _unit_key("kV/cm") == "kv/cm"


def test_semiconductor_routing_is_strong_but_cross_domain_safe(audit):
    assert set(audit["routing"]["positive"].values()) == {"semiconductors"}
    assert audit["routing"]["negative"] == {
        "photovoltaics": "photovoltaics", "thermoelectrics": "thermoelectrics",
        "batteries": "batteries", "catalysis": "catalysis",
    }
    router = DomainRouter()
    weak = "Band gap, conductivity, mobility, film, layer, current and voltage."
    try:
        assert router.route_text(weak).domain != "semiconductors"
    except ValueError:
        pass  # No supported domain is preferable to a spurious Semiconductor route.


def test_interim_audit_thirty_invariants_and_analytics(audit, archives):
    assert audit["passed"] is True and audit["passed_invariants"] == 30
    assert audit["canonical_output_total"] == 99
    assert audit["contamination"] == {"ownership": 0, "evidence": 0, "cross_record_leakage": 0, "analytics": 0}
    assert audit["live_gate"]["satisfied"] is False
    rows = [row for archive in archives.values() for row in project_results_rows(archive)
            if row["measurement_role"] == "result" and row["admission_status"] == "canonical"]
    assert len(rows) == 99
    assert all(json.loads(row["conditions_json"])["sample_label"] for row in rows)
