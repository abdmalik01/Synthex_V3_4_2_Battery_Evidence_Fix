"""Typed, loss-aware models for extracted scientific visual objects."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class BoundingBox(BaseModel):
    """PDF-space rectangle, expressed in the source page coordinate system."""

    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def _validate_order(self):
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("BoundingBox coordinates must be ordered from min to max.")
        return self


class VisualProvenance(BaseModel):
    """Locates a visual claim without asserting archive-level admissibility."""

    origin: Literal[
        "text_reported", "table_reported", "table_footnote", "figure_caption",
        "figure_annotation", "figure_digitized", "ocr_extracted",
        "supplementary_material", "web_enriched",
    ] = "table_reported"
    source_id: str | None = None
    page: int = Field(ge=1)
    object_id: str | None = None
    object_type: Literal["table", "figure", "ocr_block", "text", "unknown"] = "table"
    table_number: str | None = None
    table_or_figure_number: str | None = None
    row: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)
    cell_id: str | None = None
    panel: str | None = None
    bbox: BoundingBox | None = None
    parser_or_method: str | None = None
    # Retained during the Stage 1 → Stage 2 transition for existing callers.
    parser: str | None = None
    raw_text: str | None = None
    normalized_text: str | None = None
    verification_status: Literal["extracted", "verified_source", "candidate", "rejected"] = "extracted"
    confidence: float | None = Field(default=None, ge=0, le=1)


class TableCell(BaseModel):
    """A cell as extracted; raw text is never replaced by normalization."""

    row: int = Field(ge=0)
    column: int = Field(ge=0)
    cell_id: str | None = None
    raw_text: str | None = None
    text: str | None = None
    bbox: BoundingBox | None = None
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    provenance: VisualProvenance


class TableRecord(BaseModel):
    """A native-PDF table with raw and conservative normalized views."""

    table_id: str = Field(pattern=r"^tbl-")
    source_id: str | None = None
    page: int = Field(ge=1)
    table_number: str | None = None
    caption: str | None = None
    headers: list[list[str | None]] = Field(default_factory=list)
    header_metadata: dict[str, Any] = Field(default_factory=dict)
    rows: list[list[str | None]] = Field(default_factory=list)
    cells: list[TableCell] = Field(default_factory=list)
    column_units: dict[str, str] = Field(default_factory=dict)
    footnotes: list[str] = Field(default_factory=list)
    bbox: BoundingBox | None = None
    parser: str = "pymupdf"
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    raw_representation: dict[str, Any] = Field(default_factory=dict)
    normalized_representation: dict[str, Any] = Field(default_factory=dict)
    provenance: VisualProvenance


FigureType = Literal[
    "cycling_performance", "charge_discharge", "cyclic_voltammetry", "eis_nyquist", "tafel",
    "polarization", "xrd", "raman", "ftir", "sem", "tem", "hrtem", "xps", "uv_vis",
    "photoluminescence", "dos", "pdos", "band_structure", "heatmap", "schematic",
    "generic_plot", "other", "unknown",
]


class FigureAxis(BaseModel):
    role: Literal["x", "y", "z", "unknown"] = "unknown"
    raw_label: str | None = None
    label: str | None = None
    unit: str | None = None
    scale_type: Literal["linear", "log", "unknown"] = "unknown"


class FigurePanel(BaseModel):
    label: str
    bbox: BoundingBox | None = None
    description: str | None = None


class FigureLegendEntry(BaseModel):
    raw_label: str
    label: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class FigureAnnotation(BaseModel):
    raw_text: str
    panel: str | None = None
    bbox: BoundingBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    provenance: VisualProvenance


class FigureUnderstandingResult(BaseModel):
    """Typed provider output. It intentionally contains no digitized curve data."""

    figure_type: FigureType = "unknown"
    raw_figure_type: str | None = None
    panels: list[FigurePanel] = Field(default_factory=list)
    axes: list[FigureAxis] = Field(default_factory=list)
    legend_entries: list[FigureLegendEntry] = Field(default_factory=list)
    sample_material_labels: list[str] = Field(default_factory=list)
    context: str | None = None
    scientific_meaning: str | None = None
    annotations: list[FigureAnnotation] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


class FigureRecord(BaseModel):
    figure_id: str = Field(pattern=r"^fig-")
    source_id: str | None = None
    page: int = Field(ge=1)
    figure_number: str | None = None
    caption: str | None = None
    bbox: BoundingBox | None = None
    panels: list[FigurePanel] = Field(default_factory=list)
    figure_type: FigureType = "unknown"
    raw_figure_type: str | None = None
    axes: list[FigureAxis] = Field(default_factory=list)
    legend_entries: list[FigureLegendEntry] = Field(default_factory=list)
    annotations: list[FigureAnnotation] = Field(default_factory=list)
    sample_material_labels: list[str] = Field(default_factory=list)
    context: str | None = None
    scientific_meaning: str | None = None
    understanding_provider: str | None = None
    provider_model: str | None = None
    prompt_schema_version: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)
    raw_candidate: dict[str, Any] = Field(default_factory=dict)
    provenance: VisualProvenance


class VisualPage(BaseModel):
    page: int = Field(ge=1)
    text_parser: str | None = None
    text_sufficient: bool | None = None
    ocr_needed: bool = False
    warnings: list[str] = Field(default_factory=list)


class OCRWord(BaseModel):
    raw_text: str
    normalized_text: str | None = None
    bbox: BoundingBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class OCRTextBlock(BaseModel):
    raw_text: str
    normalized_text: str | None = None
    bbox: BoundingBox | None = None
    words: list[OCRWord] = Field(default_factory=list)


class OCRQualityReport(BaseModel):
    status: Literal["succeeded", "failed", "unavailable"]
    warnings: list[str] = Field(default_factory=list)
    engine_version: str | None = None


class OCRPageResult(BaseModel):
    source_id: str | None = None
    page: int = Field(ge=1)
    engine: str
    language: str = "eng"
    dpi: int = Field(ge=72)
    raw_text: str = ""
    normalized_text: str = ""
    blocks: list[OCRTextBlock] = Field(default_factory=list)
    quality: OCRQualityReport
    provenance: VisualProvenance | None = None


from .digitization.models import DigitizationResult


class VisualDocument(BaseModel):
    """Deterministic sidecar payload for visual objects belonging to one source."""

    source_id: str
    source_checksum: str
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)
    pages: list[VisualPage] = Field(default_factory=list)
    tables: list[TableRecord] = Field(default_factory=list)
    figures: list[FigureRecord] = Field(default_factory=list)
    ocr_blocks: list[OCRPageResult] = Field(default_factory=list)
    digitizations: list[DigitizationResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class VisualClaimCandidate(BaseModel):
    """A proposed claim; it is not a canonical measurement or admission decision."""

    raw_value_text: str
    proposed_property: str | None = None
    proposed_value: float | str | bool | None = None
    proposed_unit: str | None = None
    evidence: VisualProvenance
    verification_status: Literal["extracted", "verified_source", "candidate", "rejected"] = "candidate"
    ownership: str | None = None
    admission_status: Literal["not_submitted", "candidate", "admitted", "rejected"] = "not_submitted"
    evidence_strength: Literal["verified_native", "verified_ocr", "estimated_digitized", "unverified"] = "unverified"
