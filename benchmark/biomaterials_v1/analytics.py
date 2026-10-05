"""Specimen- and assay-preserving rows for Biomaterials benchmark comparison."""

from __future__ import annotations

from synthex_platform.extraction.biomaterials_contract import biomaterials_result_identity


def analytics_rows(archive) -> list[dict]:
    if archive.metadata.domain != "biomaterials":
        raise ValueError("Biomaterials analytics requires a biomaterials archive")
    rows = []
    for experiment in archive.experiments:
        if experiment.device_id is None or len(experiment.material_ids) != 1:
            raise ValueError("Ambiguous biomaterial experiment association")
        for measurement in experiment.outputs:
            rows.append({
                "source_id": archive.sources[0].source_id,
                "material_id": experiment.material_ids[0],
                "specimen_id": experiment.device_id,
                "experiment_id": experiment.experiment_id,
                "identity": biomaterials_result_identity(measurement),
                "property": measurement.property,
                "value": measurement.value,
                "unit": measurement.unit,
                "conditions": measurement.conditions.copy(),
                "evidence_page": measurement.evidence[0].page,
            })
    return rows
