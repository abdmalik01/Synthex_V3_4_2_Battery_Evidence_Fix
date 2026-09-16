from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.models import Evidence, ExperimentRecord, MaterialEntity, Measurement, ProcessStep, Relationship, SourceRecord
from synthex_platform.visual.analytics.projection import project_archives
from synthex_platform.visual.analytics.specs import chart_field_options, numeric_dimension_summary, surface_coverage


def _archive(index: int, synthesis_temp: float, soc: float, test_temp: float, capacity: float) -> SynthexArchive:
    source_id = f"src-{index}"
    material_id = f"mat-{index}"
    process_id = f"proc-{index}"
    experiment_id = f"exp-{index}"
    evidence = Evidence(
        source_id=source_id,
        page=1,
        source_type="text",
        text_snippet=f"fixture {index}",
        verbatim_match=True,
    )
    return SynthexArchive(
        metadata=ArchiveMetadata(archive_id=f"arc-{index}", domain="batteries"),
        sources=[SourceRecord(source_id=source_id, title=f"Paper {index}")],
        materials=[MaterialEntity(material_id=material_id, name=f"LFP-{index}")],
        processes=[ProcessStep(
            process_id=process_id,
            name="hydrothermal synthesis",
            outputs=[material_id],
            parameters=[Measurement(
                property="temperature",
                raw_value=f"{synthesis_temp} °C",
                value=synthesis_temp,
                unit="°C",
                evidence=[evidence],
            )],
            evidence=[evidence],
        )],
        experiments=[ExperimentRecord(
            experiment_id=experiment_id,
            experiment_type="battery performance / cycling",
            material_ids=[material_id],
            outputs=[Measurement(
                property="specific_capacity",
                raw_value=f"{capacity} mAh/g",
                value=capacity,
                unit="mAh/g",
                conditions={
                    "state_of_charge": {
                        "raw_value": f"{soc}% SOC",
                        "value": soc,
                        "unit": "%",
                    },
                    "temperature": {
                        "raw_value": f"{test_temp} °C",
                        "value": test_temp,
                        "unit": "°C",
                    },
                },
                evidence=[evidence],
            )],
            evidence=[evidence],
        )],
        relationships=[Relationship(
            relation_id=f"rel-{index}",
            subject_id=material_id,
            predicate="processed_by",
            object_id=process_id,
        )],
    )


def test_visual_projection_exposes_soc_and_material_process_lineage():
    row = project_archives([_archive(1, 200, 50, 25, 130)])[0]
    assert row.conditions["state_of_charge"] == 50.0
    assert row.conditions["state_of_charge_unit"] == "%"
    assert row.conditions["temperature"] == 25.0
    assert row.conditions["synthesis_temperature"] == 200.0
    assert row.conditions["synthesis_temperature_unit"] == "°C"

    options = chart_field_options([row], "scatter")
    assert "conditions.state_of_charge" in options["x"]
    assert "conditions.synthesis_temperature" in options["x"]


def test_surface_coverage_reports_joint_multidimensional_density():
    rows = project_archives([
        _archive(1, 190, 20, 25, 120),
        _archive(2, 200, 20, 45, 126),
        _archive(3, 210, 80, 25, 132),
        _archive(4, 220, 80, 45, 138),
    ])

    summary = {item["field"]: item for item in numeric_dimension_summary(rows)}
    assert summary["conditions.state_of_charge"]["observations"] == 4
    assert summary["conditions.state_of_charge"]["unique_values"] == 2
    assert summary["conditions.synthesis_temperature"]["unique_values"] == 4

    coverage = surface_coverage(
        rows,
        "conditions.state_of_charge",
        "conditions.temperature",
        "value",
    )
    assert coverage["joint_xyz"] == 4
    assert coverage["unique_x"] == 2
    assert coverage["unique_y"] == 2
    assert coverage["unique_coordinates"] == 4
