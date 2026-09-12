from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, Field, model_validator

from synthex_platform.version import __version__
from .models import (
    CalculationRecord,
    DomainPayload,
    ExperimentRecord,
    MaterialEntity,
    DeviceEntity,
    ProcessStep,
    QualityRecord,
    Relationship,
    SourceRecord,
)


class ArchiveMetadata(BaseModel):
    archive_id: str
    schema_name: str = "synthex-archive"
    schema_version: str = "3.4.0"
    software_version: str = __version__
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    generator: str = f"Synthex V{__version__}"
    extractor_model: str | None = None
    domain: str | None = None


class SynthexArchive(BaseModel):
    metadata: ArchiveMetadata
    sources: list[SourceRecord] = Field(default_factory=list)
    materials: list[MaterialEntity] = Field(default_factory=list)
    devices: list[DeviceEntity] = Field(default_factory=list)
    processes: list[ProcessStep] = Field(default_factory=list)
    experiments: list[ExperimentRecord] = Field(default_factory=list)
    calculations: list[CalculationRecord] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    domain_payloads: list[DomainPayload] = Field(default_factory=list)
    quality: QualityRecord = Field(default_factory=QualityRecord)

    @model_validator(mode="after")
    def check_references(self):
        material_ids = {x.material_id for x in self.materials}
        device_ids = {x.device_id for x in self.devices}
        process_ids = {x.process_id for x in self.processes}
        experiment_ids = {x.experiment_id for x in self.experiments}
        calculation_ids = {x.calculation_id for x in self.calculations}
        known = {
            self.metadata.archive_id,
            *(x.source_id for x in self.sources),
            *material_ids,
            *device_ids,
            *process_ids,
            *experiment_ids,
            *calculation_ids,
        }
        failures: list[str] = []
        for device in self.devices:
            missing = sorted(set(device.material_ids) - material_ids)
            if missing:
                failures.append(f"Device {device.device_id} references unknown material IDs: {missing}")
        for experiment in self.experiments:
            missing_materials = sorted(set(experiment.material_ids) - material_ids)
            referenced_devices = set(experiment.device_ids)
            if experiment.device_id:
                referenced_devices.add(experiment.device_id)
            missing_devices = sorted(referenced_devices - device_ids)
            if missing_materials:
                failures.append(
                    f"Experiment {experiment.experiment_id} references unknown material IDs: {missing_materials}"
                )
            if missing_devices:
                failures.append(
                    f"Experiment {experiment.experiment_id} references unknown device IDs: {missing_devices}"
                )
        for calculation in self.calculations:
            missing = sorted(set(calculation.material_ids) - material_ids)
            if missing:
                failures.append(
                    f"Calculation {calculation.calculation_id} references unknown material IDs: {missing}"
                )
        for process in self.processes:
            # Process inputs may be literal precursor names. Outputs in the canonical
            # archive are entity references and must resolve.
            missing = sorted(
                output for output in process.outputs
                if output not in material_ids and output not in device_ids
            )
            if missing:
                failures.append(f"Process {process.process_id} references unknown output IDs: {missing}")
        missing_relationship_ids = []
        for rel in self.relationships:
            if rel.subject_id not in known:
                missing_relationship_ids.append(rel.subject_id)
            if rel.object_id not in known:
                missing_relationship_ids.append(rel.object_id)
        if missing_relationship_ids:
            failures.append(
                f"Relationship references unknown IDs: {sorted(set(missing_relationship_ids))}"
            )
        if failures:
            raise ValueError("; ".join(failures))
        return self
