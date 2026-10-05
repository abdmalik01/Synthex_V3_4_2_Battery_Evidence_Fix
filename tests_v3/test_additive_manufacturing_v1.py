from __future__ import annotations

import pytest

from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction.additive_manufacturing_contract import (
    AM_PROPERTIES, additive_manufacturing_admission_decision,
)
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftExperiment, DraftMaterial, DraftProcess, DraftSource, ExtractedDocument,
)
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.visual.analytics.projection import project_archives


def _evidence(text: str, *, page: int = 1, locator: str = "row=1;column=value") -> Evidence:
    return Evidence(
        page=page, source_type="table", verbatim_match=True,
        text_snippet=text, table_id="tbl-am", locator=locator,
    )


def _measurement(property_name: str, raw: str, value, unit: str | None, scientific_type: str):
    return Measurement(
        property=property_name, raw_value=raw, value=value, unit=unit,
        conditions={"scientific_type": scientific_type, "data_kind": "scalar"},
        evidence=[_evidence(raw)],
    )


def test_am_manifest_has_process_result_and_energy_density_taxonomies():
    manifest = DomainRegistry().get("additive_manufacturing")
    keys = {item["key"] for item in manifest["properties"]}
    assert manifest["version"] == "1.2.0"
    assert {
        "laser_power", "scan_speed", "hatch_spacing", "layer_thickness",
        "linear_energy_density", "surface_energy_density", "volumetric_energy_density",
        "relative_density", "porosity", "melt_pool_width", "grain_size",
        "absolute_density", "void_fraction", "cell_spacing", "phase_fraction",
        "texture_coefficient",
    } <= keys
    assert manifest["mechanical_property_reuse"]["contract"] == "mechanical_v1"


@pytest.mark.parametrize(
    "text,expected_type",
    [
        (
            "In our methods, samples were produced by laser powder bed fusion (LPBF). "
            "Laser power, scan speed, and hatch spacing were varied and relative density was measured.",
            "laser_powder_bed_fusion",
        ),
        (
            "Our experiment used directed energy deposition (DED); powder feed rate and laser power "
            "were varied while porosity was measured.",
            "directed_energy_deposition",
        ),
    ],
)
def test_strong_am_method_parameter_output_combinations_route_to_am(text, expected_type):
    route = DomainRouter().route_text(text)
    assert route.domain == "additive_manufacturing"
    assert expected_type in route.paper_types
    assert "am_process_parameter_output_context" in route.focal_signals["additive_manufacturing"]


def test_generic_parameter_mentions_do_not_force_am_routing():
    text = "Laser power, scan speed, and hatch spacing were optimized in a generic thermal model."
    try:
        route = DomainRouter().route_text(text)
    except ValueError:
        return
    assert route.domain != "additive_manufacturing"


def test_focal_ded_process_chain_owns_mechanical_characterization_route():
    text = (
        "This directed energy deposition (DED) study used laser power and powder feed rate "
        "to build specimens. Yield strength, ultimate tensile strength, elongation, and "
        "hardness were measured after the additive manufacturing build."
    )
    route = DomainRouter().route_text(text)
    assert route.domain == "additive_manufacturing"
    assert "directed_energy_deposition" in route.paper_types
    assert "mechanical_characterization" in route.paper_types


def test_energy_density_families_are_not_interchangeable():
    linear = _measurement("linear_energy_density", "12 J/mm", 12.0, "J/mm", "reported_derived_metric")
    wrong_linear = _measurement("linear_energy_density", "12 J/mm3", 12.0, "J/mm3", "reported_derived_metric")
    volumetric = _measurement("volumetric_energy_density", "12 J/mm3", 12.0, "J/mm3", "reported_derived_metric")
    assert additive_manufacturing_admission_decision(linear, role="process_parameter").admitted
    assert not additive_manufacturing_admission_decision(wrong_linear, role="process_parameter").admitted
    assert additive_manufacturing_admission_decision(volumetric, role="process_parameter").admitted
    assert AM_PROPERTIES["linear_energy_density"].unit_family != AM_PROPERTIES["volumetric_energy_density"].unit_family


def test_relative_density_and_porosity_remain_distinct_reported_results():
    density = _measurement("relative_density", "98.3", 98.3, "%", "reported_measurement")
    porosity = _measurement("porosity", "1.7", 1.7, "%", "reported_measurement")
    assert additive_manufacturing_admission_decision(density, role="result").admitted
    assert additive_manufacturing_admission_decision(porosity, role="result").admitted
    assert AM_PROPERTIES["relative_density"] is not AM_PROPERTIES["porosity"]


def test_am_archive_reuses_mechanical_properties_and_preserves_build_lineage():
    material_evidence = _evidence("T1")
    draft = ExtractedDocument(
        source=DraftSource(title="Focal LPBF tensile study"),
        materials=[
            DraftMaterial(
                local_id="feedstock", name="Ti-6Al-4V powder", ownership="focal_work",
                evidence=[_evidence("Ti-6Al-4V powder")],
            ),
            DraftMaterial(
                local_id="part", name="T1 AM part", ownership="focal_work",
                evidence=[material_evidence],
            ),
        ],
        processes=[DraftProcess(
            local_id="build", name="LPBF build", family="laser_powder_bed_fusion",
            input_material_refs=["feedstock"], output_material_refs=["part"],
            parameters=[_measurement(
                "laser_power", "250", 250.0, "W", "reported_process_parameter"
            )],
            ownership="focal_work", evidence=[material_evidence],
        )],
        experiments=[DraftExperiment(
            local_id="test", experiment_type="tensile_and_density", material_refs=["part"],
            outputs=[
                _measurement("relative_density", "99.1", 99.1, "%", "reported_measurement"),
                _measurement("yield_strength", "910", 910.0, "MPa", "reported_measurement"),
            ],
            ownership="focal_work", evidence=[_evidence("99.1 and 910")],
        )],
    )
    archive = assemble_archive(draft, domain="additive_manufacturing")
    assert {item.property for item in archive.experiments[0].outputs} == {
        "relative_density", "yield_strength",
    }
    assert {item.predicate for item in archive.relationships} >= {
        "input_to", "produces", "processed_by", "tested_in",
    }
    rows = project_archives([archive])
    assert len(rows) == 2
    assert all(row.conditions["synthesis_laser_power"] == 250.0 for row in rows)


def test_am_ownership_and_value_evidence_gates_quarantine_noncanonical_objects():
    weak = Measurement(
        property="laser_power", raw_value="250", value=250.0, unit="W",
        conditions={"scientific_type": "reported_process_parameter"},
        evidence=[Evidence(page=1, source_type="table", verbatim_match=True, text_snippet="250")],
    )
    assert not additive_manufacturing_admission_decision(weak, role="process_parameter").admitted

    draft = ExtractedDocument(
        source=DraftSource(title="Review"),
        materials=[DraftMaterial(
            local_id="m", name="alloy", ownership="focal_work", evidence=[_evidence("alloy")],
        )],
        processes=[DraftProcess(
            local_id="p", name="cited LPBF build", material_refs=["m"],
            parameters=[_measurement("laser_power", "250", 250.0, "W", "reported_process_parameter")],
            ownership="cited_prior_work", evidence=[_evidence("250")],
        )],
    )
    archive = assemble_archive(draft, domain="additive_manufacturing")
    assert not archive.processes
    quarantine = archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    assert quarantine[0]["reason"] == "ownership_cited_prior_work"
