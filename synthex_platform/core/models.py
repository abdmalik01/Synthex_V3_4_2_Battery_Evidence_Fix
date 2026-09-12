from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class SourceType(str, Enum):
    text = "text"
    table = "table"
    figure = "figure"
    figure_caption = "figure_caption"
    supplementary = "supplementary"
    database = "database"
    computation = "computation"
    user = "user"
    unknown = "unknown"


class Evidence(BaseModel):
    source_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    source_type: SourceType = SourceType.unknown
    original_source_type: str | None = None
    verbatim_match: bool | None = None
    text_snippet: str | None = None
    table_id: str | None = None
    figure_id: str | None = None
    locator: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class Measurement(BaseModel):
    property: str
    raw_value: str | None = None
    value: float | str | bool | None = None
    unit: str | None = None
    normalized_value: float | str | bool | None = None
    normalized_unit: str | None = None
    uncertainty: float | None = None
    uncertainty_unit: str | None = None
    qualifier: Literal["exact", "approx", "lower_bound", "upper_bound", "range", "categorical", "unknown"] = "unknown"
    method: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)


class MaterialEntity(BaseModel):
    material_id: str
    name: str | None = None
    formula: str | None = None
    composition: dict[str, float] = Field(default_factory=dict)
    elements: list[str] = Field(default_factory=list)
    phase: str | None = None
    structure: dict[str, Any] = Field(default_factory=dict)
    morphology: dict[str, Any] = Field(default_factory=dict)
    defects: list[dict[str, Any]] = Field(default_factory=list)
    dopants: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class DeviceEntity(BaseModel):
    device_id: str
    name: str | None = None
    device_type: str
    material_ids: list[str] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class ProcessStep(BaseModel):
    process_id: str
    name: str
    family: str | None = None
    sequence_index: int | None = None
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    parameters: list[Measurement] = Field(default_factory=list)
    atmosphere: str | None = None
    equipment: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class ExperimentRecord(BaseModel):
    experiment_id: str
    experiment_type: str
    material_ids: list[str] = Field(default_factory=list)
    device_id: str | None = None
    device_ids: list[str] = Field(default_factory=list)
    target: str | None = None
    conditions: list[Measurement] = Field(default_factory=list)
    outputs: list[Measurement] = Field(default_factory=list)
    protocol: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class CalculationRecord(BaseModel):
    calculation_id: str
    calculation_type: str
    material_ids: list[str] = Field(default_factory=list)
    code: str | None = None
    method: str | None = None
    functional: str | None = None
    model: dict[str, Any] = Field(default_factory=dict)
    parameters: list[Measurement] = Field(default_factory=list)
    outputs: list[Measurement] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class Relationship(BaseModel):
    relation_id: str
    subject_id: str
    predicate: str
    object_id: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)


class SourceRecord(BaseModel):
    source_id: str
    source_type: Literal["paper", "dataset", "database", "report", "thesis", "patent", "user_upload"] = "paper"
    title: str | None = None
    doi: str | None = None
    url: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    license: str | None = None
    checksum: str | None = None


class QualityRecord(BaseModel):
    completeness: float = Field(default=0.0, ge=0, le=1)
    provenance_coverage: float = Field(default=0.0, ge=0, le=1)
    unit_normalization_coverage: float = Field(default=0.0, ge=0, le=1)
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    semantic_warnings: list[str] = Field(default_factory=list)
    validation_status: Literal[
        "unvalidated", "schema_validated", "machine_validated", "human_reviewed", "rejected"
    ] = Field(
        default="unvalidated",
        description=(
            "Validation stage. schema_validated means structural/local-schema checks passed; "
            "it does not imply scientific or human verification. machine_validated is retained "
            "only for backward-compatible archive reads."
        ),
    )


class DomainPayload(BaseModel):
    domain: str
    schema_version: str
    tags: list[str] = Field(default_factory=list)
    values: dict[str, Any] = Field(default_factory=dict)
