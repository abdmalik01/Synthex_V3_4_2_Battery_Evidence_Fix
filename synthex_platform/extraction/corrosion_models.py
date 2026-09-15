from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Ownership = Literal[
    "focal_work",
    "cited_prior_work",
    "review_summary",
    "comparison_table",
    "background",
    "example",
    "unknown",
]
Qualifier = Literal["exact", "approx", "lower_bound", "upper_bound", "range", "unknown"]
EvidenceSourceType = Literal[
    "text", "table", "figure_caption", "figure", "supplementary", "unknown"
]
OriginalSourceType = Literal[
    "native_text", "table_reported", "ocr_extracted", "figure_reported", "unknown"
]


class CorrosionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    text_snippet: str | None = None
    source_type: EvidenceSourceType = "unknown"
    original_source_type: OriginalSourceType = "unknown"
    table_id: str | None = None
    figure_id: str | None = None
    locator: str | None = None
    verbatim_match: bool | None = None


class CorrosionQuantity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_value: str
    value: float | None = None
    unit: str | None = None
    qualifier: Qualifier = "unknown"


class CorrosionSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    doi: str | None = None
    url: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    pdf_text_parser: str | None = None


class CorrosionMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_id: str
    reported_name: str | None = None
    reported_formula: str | None = None
    canonical_name: str | None = None
    material_class: Literal[
        "alloy", "pure_metal", "coating", "conversion_layer", "composite",
        "polymer", "ceramic", "other", "unknown"
    ] = "unknown"
    role: Literal["substrate", "coating", "working_electrode", "corroding_material", "other", "unknown"] = "unknown"
    composition_raw: str | None = None
    substrate_ref: str | None = None
    ownership: Ownership = "unknown"
    evidence: list[CorrosionEvidence] = Field(default_factory=list)


class SurfacePreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preparation_id: str
    material_ref: str
    ownership: Ownership = "unknown"
    grinding: str | None = None
    polishing: str | None = None
    cleaning: str | None = None
    degreasing: str | None = None
    pickling: str | None = None
    heat_treatment: str | None = None
    additional_steps: list[str] = Field(default_factory=list)
    evidence: list[CorrosionEvidence] = Field(default_factory=list)


class CoatingOrInhibitor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    treatment_id: str
    treatment_type: Literal["coating", "surface_treatment", "inhibitor", "passivation", "other"]
    reported_name: str | None = None
    material_ref: str | None = None
    substrate_ref: str | None = None
    preparation_method: str | None = None
    concentration: CorrosionQuantity | None = None
    thickness: CorrosionQuantity | None = None
    ownership: Ownership = "unknown"
    evidence: list[CorrosionEvidence] = Field(default_factory=list)


class CorrosionEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str
    medium: str | None = None
    electrolyte: str | None = None
    chloride_concentration: CorrosionQuantity | None = None
    pH: CorrosionQuantity | None = None
    temperature: CorrosionQuantity | None = None
    exposure_time: CorrosionQuantity | None = None
    atmosphere: str | None = None
    flow_or_agitation: str | None = None
    inhibitor_ref: str | None = None
    evidence: list[CorrosionEvidence] = Field(default_factory=list)


class PolarizationConditions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_electrode: str | None = None
    counter_electrode: str | None = None
    exposed_area: CorrosionQuantity | None = None
    scan_rate: CorrosionQuantity | None = None
    start_potential: CorrosionQuantity | None = None
    end_potential: CorrosionQuantity | None = None
    open_circuit_stabilization: CorrosionQuantity | None = None
    evidence: list[CorrosionEvidence] = Field(default_factory=list)


class EISConditions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_electrode: str | None = None
    exposed_area: CorrosionQuantity | None = None
    frequency_min: CorrosionQuantity | None = None
    frequency_max: CorrosionQuantity | None = None
    perturbation_amplitude: CorrosionQuantity | None = None
    dc_bias: CorrosionQuantity | None = None
    equivalent_circuit: str | None = None
    evidence: list[CorrosionEvidence] = Field(default_factory=list)


class CorrosionMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property: Literal[
        "corrosion_rate", "corrosion_current_density", "corrosion_potential",
        "polarization_resistance", "charge_transfer_resistance", "solution_resistance",
        "cpe_parameter", "double_layer_capacitance", "tafel_anodic_slope",
        "tafel_cathodic_slope", "pitting_potential", "repassivation_potential",
        "breakdown_potential", "inhibition_efficiency", "protection_efficiency",
        "mass_loss", "penetration_depth", "other"
    ]
    reported_term: str | None = None
    quantity: CorrosionQuantity
    normalization_basis: str | None = None
    method: str | None = None
    ownership: Ownership = "unknown"
    evidence: list[CorrosionEvidence] = Field(default_factory=list)


class CorrosionExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    experiment_type: Literal[
        "potentiodynamic_polarization", "linear_polarization", "eis", "immersion",
        "weight_loss", "salt_spray", "localized_corrosion", "other"
    ]
    material_refs: list[str] = Field(default_factory=list)
    environment_ref: str | None = None
    treatment_refs: list[str] = Field(default_factory=list)
    polarization_conditions: PolarizationConditions | None = None
    eis_conditions: EISConditions | None = None
    metrics: list[CorrosionMetric] = Field(default_factory=list)
    ownership: Ownership = "unknown"
    evidence: list[CorrosionEvidence] = Field(default_factory=list)


class CorrosionCalculationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property: Literal["adsorption_energy", "work_function", "charge_transfer", "binding_energy", "other"]
    reported_term: str | None = None
    quantity: CorrosionQuantity
    evidence: list[CorrosionEvidence] = Field(default_factory=list)


class CorrosionCalculation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_id: str
    calculation_type: Literal["dft", "molecular_dynamics", "quantum_chemistry", "other"]
    material_refs: list[str] = Field(default_factory=list)
    surface: str | None = None
    adsorbate_or_inhibitor: str | None = None
    method: str | None = None
    parameters: dict[str, str | float | int | bool | None] = Field(default_factory=dict)
    outputs: list[CorrosionCalculationOutput] = Field(default_factory=list)
    ownership: Ownership = "unknown"
    evidence: list[CorrosionEvidence] = Field(default_factory=list)


class CorrosionConditionConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    reported_values: list[str] = Field(min_length=2)
    resolved_value: str | None = None
    evidence: list[CorrosionEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def unresolved_by_default(self):
        if self.resolved_value is not None:
            raise ValueError("Corrosion V1 conflicts must remain unresolved unless a later explicit resolution contract is added.")
        return self


class CorrosionDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: CorrosionSource
    paper_types: list[Literal[
        "material_preparation", "coating_surface_treatment", "inhibitor_study",
        "polarization_corrosion", "impedance_eis", "immersion_weight_loss",
        "localized_corrosion", "computational_corrosion", "review"
    ]] = Field(default_factory=list)
    scope_status: Literal["supported", "out_of_scope"] = "supported"
    materials: list[CorrosionMaterial] = Field(default_factory=list)
    surface_preparations: list[SurfacePreparation] = Field(default_factory=list)
    treatments: list[CoatingOrInhibitor] = Field(default_factory=list)
    environments: list[CorrosionEnvironment] = Field(default_factory=list)
    experiments: list[CorrosionExperiment] = Field(default_factory=list)
    calculations: list[CorrosionCalculation] = Field(default_factory=list)
    condition_conflicts: list[CorrosionConditionConflict] = Field(default_factory=list)
    extraction_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_are_local(self):
        material_ids = {item.local_id for item in self.materials}
        treatment_ids = {item.treatment_id for item in self.treatments}
        environment_ids = {item.environment_id for item in self.environments}
        for prep in self.surface_preparations:
            if prep.material_ref not in material_ids:
                raise ValueError(f"Unknown surface-preparation material_ref: {prep.material_ref}")
        for treatment in self.treatments:
            if treatment.material_ref and treatment.material_ref not in material_ids:
                raise ValueError(f"Unknown treatment material_ref: {treatment.material_ref}")
            if treatment.substrate_ref and treatment.substrate_ref not in material_ids:
                raise ValueError(f"Unknown treatment substrate_ref: {treatment.substrate_ref}")
        for env in self.environments:
            if env.inhibitor_ref and env.inhibitor_ref not in treatment_ids:
                raise ValueError(f"Unknown environment inhibitor_ref: {env.inhibitor_ref}")
        for experiment in self.experiments:
            missing_materials = sorted(set(experiment.material_refs) - material_ids)
            missing_treatments = sorted(set(experiment.treatment_refs) - treatment_ids)
            if missing_materials:
                raise ValueError(f"Unknown experiment material_refs: {missing_materials}")
            if missing_treatments:
                raise ValueError(f"Unknown experiment treatment_refs: {missing_treatments}")
            if experiment.environment_ref and experiment.environment_ref not in environment_ids:
                raise ValueError(f"Unknown experiment environment_ref: {experiment.environment_ref}")
        for calculation in self.calculations:
            missing = sorted(set(calculation.material_refs) - material_ids)
            if missing:
                raise ValueError(f"Unknown calculation material_refs: {missing}")
        return self
