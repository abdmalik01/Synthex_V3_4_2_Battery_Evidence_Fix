from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from synthex_platform.extraction.domain_extractor import DomainGeminiExtractor
from synthex_platform.extraction.mechanical_provider_normalization import (
    MechanicalProviderNormalizationError,
    normalize_mechanical_provider_payload,
)


def _alternate_payload(raw_value="12.5", value=12.5):
    return {
        "materials": [{
            "local_id": "material_1", "name": "alloy", "chemical_formula": "Ni-Cr",
            "ownership": "focal_work", "description": "retained in raw output only",
        }],
        "processes": [{
            "local_id": "process_1", "name": "heat treatment", "ownership": "focal_work",
            "input_materials": ["material_1"],
            "conditions": [{"parameter": "temperature", "raw_value": "900 °C", "value": 900, "unit": "°C"}],
        }],
        "experiments": [{
            "local_id": "experiment_1", "name": "creep test", "ownership": "focal_work",
            "material_id": "material_1", "description": "reported protocol",
            "measurements": [{
                "property": "rupture_time", "raw_value": raw_value, "value": value, "unit": "h",
                "conditions": [
                    {"name": "temperature", "raw_value": "800 °C", "value": 800, "unit": "°C"},
                    {"name": "applied_stress", "raw_value": "60 MPa", "value": 60, "unit": "MPa"},
                    {"name": "scientific_type", "value": "reported_measurement"},
                ],
                "source": {"source_type": "table", "table_id": "table-2"},
            }],
        }],
    }


def test_alternate_mechanical_shape_is_normalized_without_creating_evidence():
    normalized, audit = normalize_mechanical_provider_payload(_alternate_payload())
    material = normalized["materials"][0]
    process = normalized["processes"][0]
    experiment = normalized["experiments"][0]
    output = experiment["outputs"][0]
    assert material["formula"] == "Ni-Cr" and "description" not in material
    assert process["material_refs"] == ["material_1"]
    assert process["parameters"][0]["property"] == "temperature"
    assert experiment["experiment_type"] == "creep test"
    assert experiment["material_refs"] == ["material_1"]
    assert output["conditions"]["temperature"] == 800
    assert output["conditions"]["applied_stress"] == 60
    assert output["conditions"]["normalization_source"] == "provider_structure_normalization"
    assert output["evidence"] == [{"source_type": "table", "table_id": "table-2"}]
    assert audit["scientific_values_created"] == audit["evidence_created"] == 0
    assert "material.description" in audit["raw_only_fields"]


@pytest.mark.parametrize("marker", ["N/A", "NA", "not available", "not measured", "—", "-"])
def test_explicit_missing_values_never_become_measurements(marker):
    normalized, audit = normalize_mechanical_provider_payload(_alternate_payload(marker, 1327))
    assert normalized["experiments"][0]["outputs"] == []
    assert audit["omitted_missing_measurements"] == 1


def test_nonempty_domain_value_list_is_not_silently_normalized():
    payload = _alternate_payload()
    payload["domain_values"] = [{"unsafe": "ambiguous"}]
    with pytest.raises(MechanicalProviderNormalizationError, match="domain_values"):
        normalize_mechanical_provider_payload(payload)


def test_mechanical_normalization_precedes_schema_repair():
    response = json.dumps(_alternate_payload())

    class FakeModels:
        def __init__(self):
            self.calls = []

        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(text=response)

    extractor = DomainGeminiExtractor.__new__(DomainGeminiExtractor)
    from synthex_platform.core.registry import DomainRegistry
    extractor.registry = DomainRegistry()
    extractor.model = "offline-fake"
    extractor.client = SimpleNamespace(models=FakeModels())
    archive = extractor.extract_text("mechanical source", "mechanical")
    assert len(extractor.client.models.calls) == 1
    assert extractor.last_repaired_output is None
    assert extractor.last_normalized_output is not None
    assert extractor.last_normalization_audit["normalization_source"] == "provider_structure_normalization"
    # Missing source evidence remains a scientific rejection, not a normalization shortcut.
    assert archive.experiments == []
    reasons = {
        item["reason"] for item in archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    }
    assert "no_source_evidence" in reasons
