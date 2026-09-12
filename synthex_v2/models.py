from __future__ import annotations

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class Evidence(BaseModel):
    page: Optional[int] = Field(default=None, description="1-indexed PDF page if known")
    section: Optional[str] = Field(default=None, description="Paper section such as Experimental or Results")
    text_snippet: Optional[str] = Field(default=None, description="Short verbatim evidence snippet from the paper")
    source_type: Optional[Literal["text", "table", "figure_caption", "supplementary", "unknown"]] = "unknown"
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


class Quantity(BaseModel):
    raw_value: Optional[str] = Field(default=None, description="Value exactly as reported, including symbols/qualifiers")
    value: Optional[float] = None
    unit: Optional[str] = None
    normalized_value: Optional[float] = None
    normalized_unit: Optional[str] = None


class NamedParameter(BaseModel):
    name: str
    raw_value: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    evidence: Optional[Evidence] = None


class PaperInfo(BaseModel):
    title: Optional[str] = None
    doi: Optional[str] = None
    year: Optional[int] = None
    url: Optional[str] = None


class SynthesisInfo(BaseModel):
    precursors: List[str] = Field(default_factory=list)
    solvent: Optional[str] = None
    temperature: Optional[Quantity] = None
    pH: Optional[str] = None
    reaction_time: Optional[Quantity] = None
    method: Optional[str] = None
    evidence: Optional[Evidence] = None


class DepositionInfo(BaseModel):
    method_family: Optional[str] = None
    method: Optional[str] = None
    method_variant: Optional[str] = None
    substrate: Optional[str] = None
    parameters: List[NamedParameter] = Field(default_factory=list)
    post_treatment: List[NamedParameter] = Field(default_factory=list)
    evidence: Optional[Evidence] = None


class TestingConditions(BaseModel):
    target_analyte: Optional[str] = None
    concentration: Optional[Quantity] = None
    operating_temperature: Optional[Quantity] = None
    humidity: Optional[Quantity] = None
    bias_voltage: Optional[Quantity] = None
    atmosphere: Optional[str] = None


class SensorResponse(BaseModel):
    reported_term: Optional[str] = None
    definition_as_reported: Optional[str] = None
    formula: Optional[str] = None
    value: Optional[Quantity] = None
    evidence: Optional[Evidence] = None


class Sensitivity(BaseModel):
    reported_term: Optional[str] = None
    definition_as_reported: Optional[str] = None
    formula: Optional[str] = None
    value: Optional[Quantity] = None
    concentration_range: Optional[str] = None
    canonical_interpretation: Optional[str] = Field(default=None, description="Do not silently relabel; explain interpretation if paper terminology differs")
    evidence: Optional[Evidence] = None


class SelectivityEntry(BaseModel):
    interferent: Optional[str] = None
    raw_ratio: Optional[str] = Field(default=None, description="Exact reported ratio including qualifiers such as > or ~")
    selectivity_ratio: Optional[float] = Field(default=None, description="Numeric ratio only when reported as an exact/usable number")
    target_response: Optional[float] = None
    interferent_response: Optional[float] = None
    unit: Optional[str] = None
    formula: Optional[str] = None
    evidence: Optional[Evidence] = None


class Selectivity(BaseModel):
    target_analyte: Optional[str] = None
    definition_as_reported: Optional[str] = None
    entries: List[SelectivityEntry] = Field(default_factory=list)
    qualitative_statement: Optional[str] = None
    evidence: Optional[Evidence] = None


class LimitOfDetection(BaseModel):
    value: Optional[Quantity] = None
    calculation_method: Optional[str] = None
    formula: Optional[str] = None
    sigma_definition: Optional[str] = None
    calibration_slope: Optional[str] = None
    evidence: Optional[Evidence] = None


class TimeMetric(BaseModel):
    value: Optional[Quantity] = None
    criterion: Optional[str] = Field(default=None, description="For example t90 or t95; null if paper does not specify")
    analyte: Optional[str] = None
    concentration: Optional[Quantity] = None
    operating_temperature: Optional[Quantity] = None
    evidence: Optional[Evidence] = None


class PerformanceInfo(BaseModel):
    sensor_response: Optional[SensorResponse] = None
    sensitivity: Optional[Sensitivity] = None
    selectivity: Optional[Selectivity] = None
    limit_of_detection: Optional[LimitOfDetection] = None
    response_time: Optional[TimeMetric] = None
    recovery_time: Optional[TimeMetric] = None


class SampleRecord(BaseModel):
    source_paper_title: Optional[str] = None
    source_doi: Optional[str] = None
    sample_id: Optional[str] = None
    material: Optional[str] = None
    material_category: Optional[str] = None
    composition: Optional[str] = None
    sensor_type: Optional[str] = None
    transduction_method: Optional[str] = None
    synthesis: Optional[SynthesisInfo] = None
    deposition: Optional[DepositionInfo] = None
    testing_conditions: Optional[TestingConditions] = None
    performance: Optional[PerformanceInfo] = None


class SensorRecord(BaseModel):
    paper: PaperInfo = Field(default_factory=PaperInfo)
    samples: List[SampleRecord] = Field(default_factory=list)
    extraction_notes: List[str] = Field(default_factory=list)
