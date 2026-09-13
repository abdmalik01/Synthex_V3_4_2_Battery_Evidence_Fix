from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from synthex_platform.core.models import Evidence, Measurement

GenericOwnership = Literal[
    "focal_work", "cited_prior_work", "review_summary", "comparison_table",
    "background", "example", "unknown",
]


class StrictDraftModel(BaseModel):
    """The generic extraction contract rejects unknown scientific fields."""

    model_config = ConfigDict(extra="forbid")


class DraftSource(StrictDraftModel):
    title: str | None = None
    doi: str | None = None
    url: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)


class DraftMaterial(StrictDraftModel):
    local_id: str
    name: str | None = None
    formula: str | None = None
    composition: dict[str, float] = Field(default_factory=dict)
    elements: list[str] = Field(default_factory=list)
    phase: str | None = None
    morphology: dict[str, Any] = Field(default_factory=dict)
    defects: list[dict[str, Any]] = Field(default_factory=list)
    dopants: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    ownership: GenericOwnership = "unknown"
    evidence: list[Evidence] = Field(default_factory=list)


class DraftProcess(StrictDraftModel):
    local_id: str
    name: str
    family: str | None = None
    material_refs: list[str] = Field(default_factory=list)
    parameters: list[Measurement] = Field(default_factory=list)
    atmosphere: str | None = None
    equipment: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    ownership: GenericOwnership = "unknown"


class DraftExperiment(StrictDraftModel):
    local_id: str
    experiment_type: str
    material_refs: list[str] = Field(default_factory=list)
    target: str | None = None
    conditions: list[Measurement] = Field(default_factory=list)
    outputs: list[Measurement] = Field(default_factory=list)
    protocol: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    ownership: GenericOwnership = "unknown"


class DraftCalculation(StrictDraftModel):
    local_id: str
    calculation_type: str
    material_refs: list[str] = Field(default_factory=list)
    code: str | None = None
    method: str | None = None
    functional: str | None = None
    model: dict[str, Any] = Field(default_factory=dict)
    parameters: list[Measurement] = Field(default_factory=list)
    outputs: list[Measurement] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    ownership: GenericOwnership = "unknown"


class ExtractedDocument(StrictDraftModel):
    source: DraftSource = Field(default_factory=DraftSource)
    materials: list[DraftMaterial] = Field(default_factory=list)
    processes: list[DraftProcess] = Field(default_factory=list)
    experiments: list[DraftExperiment] = Field(default_factory=list)
    calculations: list[DraftCalculation] = Field(default_factory=list)
    domain_values: dict[str, Any] = Field(default_factory=dict)
    extraction_notes: list[str] = Field(default_factory=list)
