"""Strict Stage 1 data contracts for Catalysis / Electrocatalysis V1.

These models preserve reported terminology and provenance but intentionally do
not perform canonical admission, potential conversion, or unit normalization.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .draft_models import GenericOwnership


class StrictCatalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


QuantityQualifier = Literal["exact", "approx", "lower_bound", "upper_bound", "range", "unknown"]
CatalystState = Literal[
    "as_synthesized", "pretreated", "activated", "under_reaction", "post_reaction",
    "spent", "regenerated", "unknown",
]
ScopeStatus = Literal["supported", "deferred_subtype", "out_of_scope"]
ReactionClass = Literal[
    "co_oxidation", "hydrogenation", "oxidation", "methane_conversion", "ammonia_synthesis",
    "ammonia_decomposition", "hydrocarbon_conversion", "her", "oer", "orr", "co2rr", "nrr",
    "small_molecule_oxidation", "other_heterogeneous", "unknown",
]
PotentialReference = Literal["RHE", "SHE", "NHE", "Ag/AgCl", "SCE", "Hg/HgO", "Hg/Hg2SO4", "other", "unknown"]
ConversionStatus = Literal["not_attempted", "author_reported", "deterministic", "incomplete", "rejected"]
NormalizationKind = Literal[
    "geometric_area", "ecsa", "catalyst_mass", "active_component_mass", "precious_metal_mass",
    "bet_surface_area", "site_count", "reactor_volume", "unknown",
]


class CatalysisQuantity(StrictCatalysisModel):
    raw_value: str | None = None
    value: float | None = None
    unit: str | None = None
    qualifier: QuantityQualifier = "unknown"


class CatalysisEvidence(StrictCatalysisModel):
    source_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    text_snippet: str | None = None
    source_type: Literal["text", "table", "figure_caption", "figure", "supplementary", "unknown"] = "unknown"
    original_source_type: Literal[
        "native_text", "table_reported", "figure_caption", "figure_annotation",
        "ocr_extracted", "figure_digitized", "supplementary_material", "unknown",
    ] = "unknown"
    table_id: str | None = None
    figure_id: str | None = None
    locator: str | None = None
    verbatim_match: bool | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_strength: Literal["verified_native", "verified_ocr", "estimated_digitized", "unverified"] = "unverified"
    estimated: bool = False
    digitization_id: str | None = None


class CatalysisDerivation(StrictCatalysisModel):
    reported_property: str
    reported_raw_value: str
    reported_value: float | None = None
    transformation: str


class CatalysisConflictValue(StrictCatalysisModel):
    raw_value: str
    evidence: list[CatalysisEvidence] = Field(default_factory=list)


class CatalysisConditionConflict(StrictCatalysisModel):
    field: Literal[
        "catalyst_loading", "temperature", "reference_electrode", "normalization_basis",
        "electrolyte_concentration", "reaction_condition", "stability_duration", "other",
    ]
    record_ref: str | None = None
    status: Literal["conflicted"] = "conflicted"
    reported_values: list[CatalysisConflictValue] = Field(min_length=2)
    resolved_value: str | None = None


class NormalizationBasis(StrictCatalysisModel):
    kind: NormalizationKind = "unknown"
    reported_basis: str | None = None
    denominator_value: float | None = None
    denominator_unit: str | None = None
    material_ref: str | None = None
    comparison_status: Literal["comparable", "unknown_basis", "not_comparable"] = "unknown_basis"

    @model_validator(mode="after")
    def _status_matches_basis(self):
        if self.kind == "unknown" and self.comparison_status == "comparable":
            raise ValueError("An unknown normalization basis cannot be marked comparable.")
        return self


class CatalystComponent(StrictCatalysisModel):
    role: Literal["active_component", "support", "promoter", "dopant", "binder", "other", "unknown"] = "unknown"
    reported_name: str | None = None
    formula: str | None = None
    material_ref: str | None = None
    loading: CatalysisQuantity | None = None
    loading_basis: str | None = None
    evidence: list[CatalysisEvidence] = Field(default_factory=list)


class ActiveSiteClaim(StrictCatalysisModel):
    reported_description: str
    canonical_description: str | None = None
    basis: Literal["reported_characterization", "reported_computation", "author_hypothesis", "unknown"] = "unknown"
    evidence: list[CatalysisEvidence] = Field(default_factory=list)


class CatalystMaterial(StrictCatalysisModel):
    local_id: str
    reported_name: str | None = None
    canonical_name: str | None = None
    reported_formula: str | None = None
    formula: str | None = None
    composition_raw: str | None = None
    composition: dict[str, float] = Field(default_factory=dict)
    catalyst_family: str | None = None
    state: CatalystState = "unknown"
    state_parent_ref: str | None = None
    variant_of: str | None = None
    components: list[CatalystComponent] = Field(default_factory=list)
    phase: str | None = None
    particle_size: CatalysisQuantity | None = None
    morphology: str | None = None
    bet_surface_area: CatalysisQuantity | None = None
    pore_size: CatalysisQuantity | None = None
    pore_volume: CatalysisQuantity | None = None
    oxidation_state: str | None = None
    exposed_facet: str | None = None
    active_site_claims: list[ActiveSiteClaim] = Field(default_factory=list)
    ownership: GenericOwnership = "unknown"
    evidence: list[CatalysisEvidence] = Field(default_factory=list)


class CatalystPreparationStep(StrictCatalysisModel):
    step: Literal[
        "mixing", "impregnation", "deposition", "precipitation", "hydrothermal", "solvothermal",
        "washing", "drying", "calcination", "annealing", "reduction", "activation", "pretreatment", "other",
    ]
    details: str | None = None
    precursors: list[str] = Field(default_factory=list)
    precursor_ratio_raw: str | None = None
    solvents: list[str] = Field(default_factory=list)
    pH: float | None = None
    temperature: CatalysisQuantity | None = None
    duration: CatalysisQuantity | None = None
    atmosphere: str | None = None
    evidence: list[CatalysisEvidence] = Field(default_factory=list)


class CatalystPreparation(StrictCatalysisModel):
    preparation_id: str
    material_ref: str | None = None
    name: str | None = None
    ownership: GenericOwnership = "unknown"
    steps: list[CatalystPreparationStep] = Field(default_factory=list)
    evidence: list[CatalysisEvidence] = Field(default_factory=list)


class CharacterizationResult(StrictCatalysisModel):
    property: str
    raw_value: str | None = None
    value: float | None = None
    unit: str | None = None
    qualifier: QuantityQualifier = "unknown"
    evidence: list[CatalysisEvidence] = Field(default_factory=list)


class CatalystCharacterization(StrictCatalysisModel):
    characterization_id: str
    material_ref: str | None = None
    method: str
    conditions: dict[str, Any] = Field(default_factory=dict)
    results: list[CharacterizationResult] = Field(default_factory=list)
    ownership: GenericOwnership = "unknown"
    evidence: list[CatalysisEvidence] = Field(default_factory=list)


class ReactionSpecies(StrictCatalysisModel):
    reported_name: str
    formula: str | None = None


class ReactionDefinition(StrictCatalysisModel):
    reported_reaction: str | None = None
    reaction_class: ReactionClass = "unknown"
    reactants: list[ReactionSpecies] = Field(default_factory=list)
    products: list[ReactionSpecies] = Field(default_factory=list)


class FeedComponent(StrictCatalysisModel):
    species: str
    fraction: CatalysisQuantity | None = None
    basis: str | None = None


class HeterogeneousMetric(StrictCatalysisModel):
    property: Literal[
        "conversion", "selectivity", "yield", "activity", "reaction_rate", "turnover_frequency",
        "productivity", "activation_energy", "carbon_balance",
    ]
    raw_value: str | None = None
    value: float | None = None
    unit: str | None = None
    qualifier: QuantityQualifier = "unknown"
    reactant: str | None = None
    product: str | None = None
    normalization_basis: NormalizationBasis | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    derivation: CatalysisDerivation | None = None
    ownership: GenericOwnership = "unknown"
    evidence: list[CatalysisEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _required_species(self):
        if self.property == "conversion" and not self.reactant:
            raise ValueError("Conversion must identify its reactant.")
        if self.property in {"selectivity", "yield"} and not self.product:
            raise ValueError(f"{self.property} must identify its product.")
        return self


class HeterogeneousCatalysisExperiment(StrictCatalysisModel):
    experiment_id: str
    catalyst_ref: str | None = None
    reaction: ReactionDefinition
    reactor_type: str | None = None
    catalyst_mass: CatalysisQuantity | None = None
    feed_composition: list[FeedComponent] = Field(default_factory=list)
    flow_rate: CatalysisQuantity | None = None
    whsv: CatalysisQuantity | None = None
    ghsv: CatalysisQuantity | None = None
    pressure: CatalysisQuantity | None = None
    temperature: CatalysisQuantity | None = None
    carrier_gas: str | None = None
    pretreatment_ref: str | None = None
    reaction_time: CatalysisQuantity | None = None
    time_on_stream: CatalysisQuantity | None = None
    analytical_method: str | None = None
    metrics: list[HeterogeneousMetric] = Field(default_factory=list)
    ownership: GenericOwnership = "unknown"
    evidence: list[CatalysisEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _non_negative_mass(self):
        if self.catalyst_mass and self.catalyst_mass.value is not None and self.catalyst_mass.value < 0:
            raise ValueError("Catalyst mass cannot be negative.")
        return self


class ElectrochemicalPotential(StrictCatalysisModel):
    raw_potential: CatalysisQuantity | None = None
    reported_reference: PotentialReference = "unknown"
    reported_reference_text: str | None = None
    filling_solution: str | None = None
    filling_solution_concentration: CatalysisQuantity | None = None
    pH: float | None = None
    temperature: CatalysisQuantity | None = None
    converted_potential: CatalysisQuantity | None = None
    converted_reference: PotentialReference | None = None
    conversion_status: ConversionStatus = "not_attempted"
    author_formula: str | None = None

    @model_validator(mode="after")
    def _conversion_is_explicit(self):
        if (self.converted_potential is not None or self.converted_reference is not None) and self.conversion_status not in {"author_reported", "deterministic"}:
            raise ValueError("Converted potentials require author_reported or deterministic conversion status.")
        return self


class ElectrocatalyticMetric(StrictCatalysisModel):
    property: Literal[
        "overpotential", "onset_potential", "half_wave_potential", "current_density",
        "partial_current_density", "tafel_slope", "faradaic_efficiency", "product_selectivity",
        "mass_activity", "specific_activity", "turnover_frequency", "ecsa",
        "double_layer_capacitance", "product_formation_rate", "retention",
    ]
    raw_value: str | None = None
    value: float | None = None
    unit: str | None = None
    qualifier: QuantityQualifier = "unknown"
    product: str | None = None
    potential: ElectrochemicalPotential | None = None
    applied_current: CatalysisQuantity | None = None
    normalization_basis: NormalizationBasis | None = None
    duration: CatalysisQuantity | None = None
    analytical_method: str | None = None
    derivation: CatalysisDerivation | None = None
    ownership: GenericOwnership = "unknown"
    evidence: list[CatalysisEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _product_metrics_have_products(self):
        if self.property in {"faradaic_efficiency", "product_selectivity", "partial_current_density", "product_formation_rate"} and not self.product:
            raise ValueError(f"{self.property} must identify its product.")
        return self


class ElectrocatalysisExperiment(StrictCatalysisModel):
    experiment_id: str
    catalyst_ref: str | None = None
    reaction: ReactionDefinition
    working_electrode: str | None = None
    catalyst_loading: CatalysisQuantity | None = None
    substrate_or_current_collector: str | None = None
    binder: str | None = None
    geometric_area: CatalysisQuantity | None = None
    electrolyte: str | None = None
    electrolyte_concentration: CatalysisQuantity | None = None
    pH: float | None = None
    temperature: CatalysisQuantity | None = None
    cell_configuration: str | None = None
    membrane: str | None = None
    reference_electrode: str | None = None
    counter_electrode: str | None = None
    rotation_speed: CatalysisQuantity | None = None
    scan_rate: CatalysisQuantity | None = None
    potential_window: str | None = None
    controlled_potential: ElectrochemicalPotential | None = None
    controlled_current: CatalysisQuantity | None = None
    ir_compensation: str | None = None
    metrics: list[ElectrocatalyticMetric] = Field(default_factory=list)
    ownership: GenericOwnership = "unknown"
    evidence: list[CatalysisEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _non_negative_loading(self):
        if self.catalyst_loading and self.catalyst_loading.value is not None and self.catalyst_loading.value < 0:
            raise ValueError("Catalyst loading cannot be negative.")
        return self


class StabilityTest(StrictCatalysisModel):
    stability_id: str
    experiment_ref: str | None = None
    mode: Literal["time_on_stream", "chronopotentiometry", "chronoamperometry", "cycling", "regeneration", "other"] = "other"
    duration: CatalysisQuantity | None = None
    cycle_count: int | None = Field(default=None, ge=0)
    operating_potential: ElectrochemicalPotential | None = None
    operating_current: CatalysisQuantity | None = None
    retained_metric: HeterogeneousMetric | ElectrocatalyticMetric | None = None
    conversion_loss: CatalysisQuantity | None = None
    structural_changes: list[str] = Field(default_factory=list)
    regeneration_details: str | None = None
    ownership: GenericOwnership = "unknown"
    evidence: list[CatalysisEvidence] = Field(default_factory=list)


class ComputationalMetric(StrictCatalysisModel):
    property: Literal[
        "adsorption_energy", "adsorption_free_energy", "reaction_free_energy", "activation_barrier",
        "transition_state_energy", "d_band_center", "work_function", "bader_charge",
        "charge_density_difference", "dos_pdos", "surface_energy", "vacancy_formation_energy",
        "binding_energy", "limiting_potential", "theoretical_overpotential",
    ]
    raw_value: str | None = None
    value: float | None = None
    unit: str | None = None
    qualifier: QuantityQualifier = "unknown"
    adsorbate_or_intermediate: str | None = None
    site: str | None = None
    facet: str | None = None
    ownership: GenericOwnership = "unknown"
    evidence: list[CatalysisEvidence] = Field(default_factory=list)


class CatalysisCalculation(StrictCatalysisModel):
    calculation_id: str
    material_refs: list[str] = Field(default_factory=list)
    calculation_type: Literal["dft", "first_principles", "other"] = "dft"
    code: str | None = None
    functional: str | None = None
    dispersion_correction: str | None = None
    plane_wave_cutoff_or_basis: str | None = None
    k_points: str | None = None
    slab_or_facet: str | None = None
    layers: int | None = Field(default=None, ge=1)
    vacuum_thickness: CatalysisQuantity | None = None
    solvation_model: str | None = None
    adsorbate_coverage: str | None = None
    spin_treatment: str | None = None
    outputs: list[ComputationalMetric] = Field(default_factory=list)
    ownership: GenericOwnership = "unknown"
    evidence: list[CatalysisEvidence] = Field(default_factory=list)


class CatalysisSource(StrictCatalysisModel):
    title: str | None = None
    doi: str | None = None
    url: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    pdf_text_parser: Literal["pypdf", "pymupdf"] | None = None


class CatalysisDocument(StrictCatalysisModel):
    source: CatalysisSource = Field(default_factory=CatalysisSource)
    paper_types: list[Literal[
        "catalyst_synthesis", "catalyst_characterization", "heterogeneous_catalysis", "electrocatalysis",
        "kinetics", "stability_deactivation", "computational_dft", "catalyst_dataset_modelling", "review",
    ]] = Field(default_factory=list)
    scope_status: ScopeStatus = "supported"
    catalysts: list[CatalystMaterial] = Field(default_factory=list)
    preparations: list[CatalystPreparation] = Field(default_factory=list)
    characterizations: list[CatalystCharacterization] = Field(default_factory=list)
    heterogeneous_experiments: list[HeterogeneousCatalysisExperiment] = Field(default_factory=list)
    electrocatalysis_experiments: list[ElectrocatalysisExperiment] = Field(default_factory=list)
    stability_tests: list[StabilityTest] = Field(default_factory=list)
    calculations: list[CatalysisCalculation] = Field(default_factory=list)
    condition_conflicts: list[CatalysisConditionConflict] = Field(default_factory=list)
    extraction_notes: list[str] = Field(default_factory=list)
    semantic_warnings: list[str] = Field(default_factory=list)


def collect_stage1_warnings(document: CatalysisDocument) -> list[str]:
    """Return deterministic warnings without correcting any reported scientific value."""
    warnings: list[str] = []

    def percentage_warning(record_id: str, metric) -> None:
        if metric.unit == "%" and metric.value is not None and metric.value > 100:
            warnings.append(f"{record_id}.{metric.property}: percentage_greater_than_100")
        if metric.normalization_basis and metric.normalization_basis.kind == "unknown":
            warnings.append(f"{record_id}.{metric.property}: normalization_basis_unknown")
        if metric.property in {"onset_potential", "half_wave_potential", "current_density", "partial_current_density", "faradaic_efficiency", "product_selectivity", "mass_activity", "specific_activity"}:
            if metric.potential and metric.potential.reported_reference == "unknown":
                warnings.append(f"{record_id}.{metric.property}: potential_reference_unknown")

    for experiment in document.heterogeneous_experiments:
        for metric in experiment.metrics:
            percentage_warning(experiment.experiment_id, metric)
    for experiment in document.electrocatalysis_experiments:
        if experiment.pH is not None and not 0 <= experiment.pH <= 14:
            warnings.append(f"{experiment.experiment_id}: pH_outside_0_to_14")
        for metric in experiment.metrics:
            percentage_warning(experiment.experiment_id, metric)
    return list(dict.fromkeys(warnings))


def with_stage1_warnings(document: CatalysisDocument) -> CatalysisDocument:
    warnings = [*document.semantic_warnings, *collect_stage1_warnings(document)]
    return document.model_copy(update={"semantic_warnings": list(dict.fromkeys(warnings))})
