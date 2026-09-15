from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from synthex_platform.core.registry import DomainRegistry


@dataclass(frozen=True)
class DomainRoute:
    domain: str
    confidence: float
    scores: dict[str, float]
    matched_terms: dict[str, list[str]]
    paper_types: list[str]
    method: str = "lexical_router_v1"
    focal_signals: dict[str, list[str]] | None = None
    incidental_signals: dict[str, list[str]] | None = None
    ambiguity_reason: str | None = None
    scope_status: str = "supported"


DOMAIN_TERMS: dict[str, tuple[str, ...]] = {
    "batteries": (
        "lithium-ion", "li-ion", "battery", "batteries", "cathode", "anode",
        "electrolyte", "charge-discharge", "charge discharge", "coulombic",
        "capacity retention", "c-rate", "state of health", "state-of-health",
        "constant current", "constant voltage", "electrochemical impedance spectroscopy",
    ),
    "gas_sensing": (
        "gas sensor", "gas sensing", "chemiresistive", "target gas", "response time",
        "recovery time", "selectivity", "ppm", "ppb", "sensor response", "gas response",
        "operating temperature", "ra/rg", "ra / rg", "resistance ratio", "discriminability",
    ),
    "catalysis": (
        "catalyst", "catalysis", "electrocatalysis", "overpotential", "tafel slope",
        "faradaic efficiency", "turnover frequency", "oer", "her", "orr", "co2rr", "nrr",
        "co oxidation", "hydrogenation", "methane conversion", "ammonia synthesis",
        "ammonia decomposition", "conversion", "product selectivity", "yield", "reactor",
        "whsv", "ghsv", "time on stream", "adsorption energy", "adsorption free energy",
        "reaction free energy", "d-band center", "limiting potential", "surface slab",
    ),
    "corrosion": (
        "corrosion", "corrosion rate", "pitting", "pitting potential", "repassivation",
        "breakdown potential", "icorr", "i_corr", "ecorr", "e_corr",
        "polarization resistance", "potentiodynamic polarization", "linear polarization resistance",
        "corrosion current density", "corrosion potential", "weight loss", "mass loss",
        "salt spray", "inhibition efficiency", "corrosion inhibitor", "protective coating",
        "electrochemical impedance spectroscopy", "nyquist", "charge transfer resistance",
        "chloride solution", "nacl solution", "passivation", "passive film",
    ),
    "mechanical": (
        "yield strength", "ultimate tensile", "fatigue", "creep", "rupture life",
        "stress-strain", "stress strain", "elongation",
    ),
    "additive_manufacturing": (
        "additive manufacturing", "selective laser melting", "laser powder bed fusion",
        "lpbf", "slm", "scan speed", "hatch spacing", "melt pool",
    ),
    "photovoltaics": (
        "photovoltaic", "solar cell", "power conversion efficiency", "open-circuit voltage",
        "short-circuit current", "fill factor", "eqe",
    ),
    "thermoelectrics": (
        "thermoelectric", "seebeck", "figure of merit", "zt", "power factor",
    ),
    "membranes": (
        "membrane", "permeability", "permeance", "rejection", "separation factor", "flux",
    ),
    "semiconductors": (
        "semiconductor", "carrier mobility", "carrier concentration", "effective mass",
        "band gap", "bandgap", "defect formation energy",
    ),
    "biomaterials": (
        "biomaterial", "biocompatibility", "cell viability", "hemolysis", "osseointegration",
        "cytotoxicity", "bioactivity",
    ),
}

BATTERY_PAPER_TYPE_TERMS: dict[str, tuple[str, ...]] = {
    "materials_synthesis": ("synthesis", "calcination", "precursor", "sol-gel", "hydrothermal"),
    "electrode_fabrication": ("electrode preparation", "slurry", "binder", "current collector", "coating"),
    "cell_assembly": ("coin cell", "pouch cell", "cell assembly", "separator", "glovebox"),
    "electrochemical_performance": ("charge", "discharge", "capacity", "cycling", "coulombic efficiency"),
    "degradation_health": ("degradation", "state of health", "state-of-health", "capacity fading", "aging", "ageing"),
    "impedance_eis": ("impedance", "electrochemical impedance spectroscopy", "eis", "nyquist"),
    "computational_dft": ("density functional theory", "dft", "migration barrier", "formation energy"),
    "battery_dataset_modelling": ("dataset", "data set", "prognostics", "prediction", "machine learning", "model"),
}

CATALYSIS_PAPER_TYPE_TERMS: dict[str, tuple[str, ...]] = {
    "catalyst_synthesis": ("impregnation", "calcination", "reduction", "precursor", "catalyst preparation"),
    "catalyst_characterization": ("xrd", "xps", "bet surface area", "raman", "tem", "sem"),
    "heterogeneous_catalysis": ("reactor", "conversion", "selectivity", "whsv", "ghsv", "time on stream"),
    "electrocatalysis": ("electrocatalysis", "overpotential", "tafel slope", "faradaic efficiency", "reference electrode", "rhe"),
    "kinetics": ("activation energy", "reaction rate", "turnover frequency", "tafel slope"),
    "stability_deactivation": ("deactivation", "regeneration", "stability", "time on stream", "retention"),
    "computational_dft": ("density functional theory", "dft", "adsorption energy", "free energy", "d-band center"),
    "catalyst_dataset_modelling": ("catalyst dataset", "catalysis dataset", "catalyst database", "activity prediction"),
    "review": ("review", "perspective", "overview"),
}

CORROSION_PAPER_TYPE_TERMS: dict[str, tuple[str, ...]] = {
    "material_preparation": ("alloy", "substrate", "grinding", "polishing", "heat treatment", "solution treatment"),
    "coating_surface_treatment": ("coating", "electrodeposition", "anodizing", "conversion coating", "surface treatment", "passivation"),
    "inhibitor_study": ("corrosion inhibitor", "inhibition efficiency", "inhibitor concentration", "adsorption isotherm"),
    "polarization_corrosion": ("potentiodynamic polarization", "tafel", "icorr", "ecorr", "polarization resistance", "linear polarization"),
    "impedance_eis": ("electrochemical impedance spectroscopy", "eis", "nyquist", "bode", "charge transfer resistance", "equivalent circuit"),
    "immersion_weight_loss": ("immersion", "weight loss", "mass loss", "corrosion rate", "exposure time"),
    "localized_corrosion": ("pitting", "pitting potential", "repassivation", "breakdown potential", "crevice corrosion"),
    "computational_corrosion": ("density functional theory", "dft", "adsorption energy", "work function", "molecular dynamics", "quantum chemical"),
    "review": ("review", "perspective", "overview"),
}

_CATALYSIS_DEFERRED_TERMS = ("photocatalysis", "photocatalyst", "homogeneous catalysis", "molecular catalyst", "enzymatic catalysis", "biocatalysis")
_HETERO_REACTION_TERMS = ("co oxidation", "hydrogenation", "methane conversion", "ammonia synthesis", "ammonia decomposition", "hydrocarbon conversion", "oxidation")
_HETERO_OPERATION_TERMS = ("reactor", "conversion", "selectivity", "yield", "whsv", "ghsv", "feed composition", "time on stream")
_ELECTRO_REACTION_TERMS = ("her", "oer", "orr", "co2rr", "nrr", "small molecule oxidation")
_ELECTRO_OPERATION_TERMS = ("overpotential", "tafel slope", "faradaic efficiency", "reference electrode", "rhe", "ag/agcl", "electrolyte", "current density")
_DFT_SURFACE_TERMS = ("surface", "slab", "facet", "adsorbate", "intermediate")
_DFT_METHOD_TERMS = ("density functional theory", "dft", "k points", "functional", "plane wave")
_DFT_PROPERTY_TERMS = ("adsorption energy", "adsorption free energy", "reaction free energy", "activation barrier", "d-band center", "limiting potential")
_CORROSION_ELECTROCHEM_TERMS = (
    "potentiodynamic polarization", "linear polarization resistance", "icorr", "ecorr",
    "corrosion current density", "corrosion potential", "pitting potential",
)
_CORROSION_ENVIRONMENT_TERMS = (
    "nacl", "chloride", "electrolyte", "immersion", "salt spray", "corrosive environment",
)
_CORROSION_PERFORMANCE_TERMS = (
    "corrosion rate", "inhibition efficiency", "polarization resistance", "charge transfer resistance",
    "weight loss", "mass loss", "pitting", "passive film",
)

MATERIALS_INFORMATICS_TERMS: tuple[str, ...] = (
    "knowledge graph", "named entity recognition", "ner", "bert", "dataset", "data set",
    "rdf", "sparql", "literature mining", "ontology", "corpus", "database", "triples",
    "information extraction",
)
_MATERIALS_INFORMATICS_PRIMARY_TERMS = (
    "knowledge graph", "named entity recognition", "rdf", "sparql", "literature mining",
    "ontology", "triples", "information extraction",
)
_INCIDENTAL_CUES = ("for example", "example", "cited", "previously reported", "prior work", "literature example", "review")
_FOCAL_CUES = (
    "we synthesized", "we prepared", "we measured", "our experiment", "experimental section",
    "methods", "reaction conditions", "electrochemical measurement", "we exposed",
    "specimens were", "samples were", "polarization tests", "eis measurements",
)
_MIN_SCIENTIFIC_DOMAIN_SCORE = 4.0


def _count_term(text: str, term: str) -> int:
    escaped = re.escape(term)
    if len(term) <= 4 and " " not in term and "-" not in term:
        return len(re.findall(rf"\b{escaped}\b", text, flags=re.IGNORECASE))
    return len(re.findall(escaped, text, flags=re.IGNORECASE))


def _matched(text: str, terms: Iterable[str]) -> tuple[float, list[str]]:
    score = 0.0
    hits: list[str] = []
    for term in terms:
        n = _count_term(text, term)
        if n:
            hits.append(term)
            score += 1.0 + min(n - 1, 4) * 0.25
    return score, hits


def _contextual_signals(text: str, terms: Iterable[str]) -> tuple[list[str], list[str]]:
    focal, incidental = [], []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        lowered = sentence.lower()
        matched = [term for term in terms if _count_term(sentence, term)]
        if not matched:
            continue
        if any(cue in lowered for cue in _INCIDENTAL_CUES):
            incidental.extend(matched)
        elif any(cue in lowered for cue in _FOCAL_CUES):
            focal.extend(matched)
    return sorted(set(focal)), sorted(set(incidental))


def classify_battery_paper_types(text: str) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for paper_type, terms in BATTERY_PAPER_TYPE_TERMS.items():
        score, _ = _matched(text, terms)
        if score > 0:
            ranked.append((score, paper_type))
    ranked.sort(reverse=True)
    return [name for score, name in ranked if score >= 1.0][:5]


def classify_catalysis_paper_types(text: str) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for paper_type, terms in CATALYSIS_PAPER_TYPE_TERMS.items():
        score, _ = _matched(text, terms)
        if score > 0:
            ranked.append((score, paper_type))
    ranked.sort(reverse=True)
    return [name for score, name in ranked if score >= 1.0][:6]


def classify_corrosion_paper_types(text: str) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for paper_type, terms in CORROSION_PAPER_TYPE_TERMS.items():
        score, _ = _matched(text, terms)
        if score > 0:
            ranked.append((score, paper_type))
    ranked.sort(reverse=True)
    return [name for score, name in ranked if score >= 1.0][:6]


def catalysis_scope_status(text: str) -> str:
    title_and_abstract = text[:6000]
    deferred_score, _ = _matched(title_and_abstract, _CATALYSIS_DEFERRED_TERMS)
    return "deferred_subtype" if deferred_score >= 1.25 else "supported"


def _has_materials_informatics_context(text: str, hits: list[str]) -> bool:
    primary_hits = [term for term in _MATERIALS_INFORMATICS_PRIMARY_TERMS if term in hits]
    has_named_entity_pair = "named entity recognition" in hits or (
        "ner" in hits and any(term in hits for term in ("bert", "corpus", "information extraction"))
    )
    has_model_data_pair = "bert" in hits and any(term in hits for term in ("dataset", "data set", "corpus", "database"))
    return bool((primary_hits and len(hits) >= 2) or has_named_entity_pair or has_model_data_pair)


def _catalysis_context_bonus(text: str) -> tuple[float, list[str]]:
    catalyst_score, _ = _matched(text, ("catalyst", "catalysis", "electrocatalysis"))
    hetero_reaction, _ = _matched(text, _HETERO_REACTION_TERMS)
    hetero_operation, _ = _matched(text, _HETERO_OPERATION_TERMS)
    electro_reaction, _ = _matched(text, _ELECTRO_REACTION_TERMS)
    electro_operation, _ = _matched(text, _ELECTRO_OPERATION_TERMS)
    dft_surface, _ = _matched(text, _DFT_SURFACE_TERMS)
    dft_method, _ = _matched(text, _DFT_METHOD_TERMS)
    dft_property, _ = _matched(text, _DFT_PROPERTY_TERMS)
    signals: list[str] = []
    bonus = 0.0
    if catalyst_score and hetero_reaction and hetero_operation:
        bonus = max(bonus, 3.5)
        signals.append("heterogeneous_context")
    if electro_reaction and electro_operation:
        bonus = max(bonus, 3.5)
        signals.append("electrocatalysis_context")
    if dft_surface and dft_method and dft_property:
        bonus = max(bonus, 3.5)
        signals.append("computational_catalysis_context")
    return bonus, signals


def _corrosion_context_bonus(text: str) -> tuple[float, list[str]]:
    corrosion_score, _ = _matched(text, ("corrosion", "corrosion rate", "corrosion inhibitor", "pitting"))
    electrochem_score, _ = _matched(text, _CORROSION_ELECTROCHEM_TERMS)
    environment_score, _ = _matched(text, _CORROSION_ENVIRONMENT_TERMS)
    performance_score, _ = _matched(text, _CORROSION_PERFORMANCE_TERMS)
    signals: list[str] = []
    bonus = 0.0
    if corrosion_score and environment_score and performance_score:
        bonus = max(bonus, 3.0)
        signals.append("corrosion_environment_performance_context")
    if corrosion_score and electrochem_score:
        bonus = max(bonus, 3.5)
        signals.append("electrochemical_corrosion_context")
    return bonus, signals


class DomainRouter:
    """Fast, deterministic first-pass domain router with no LLM dependency."""

    def __init__(self, registry: DomainRegistry | None = None):
        self.registry = registry or DomainRegistry()

    def route_text(self, text: str) -> DomainRoute:
        if not text or not text.strip():
            raise ValueError("Cannot route empty text.")

        available = {d["slug"] for d in self.registry.list_domains()}
        scores: dict[str, float] = {}
        matched_terms: dict[str, list[str]] = {}
        focal_signals: dict[str, list[str]] = {}
        incidental_signals: dict[str, list[str]] = {}

        for domain in sorted(available):
            score, hits = _matched(text, DOMAIN_TERMS.get(domain, ()))
            focal, incidental = _contextual_signals(text, DOMAIN_TERMS.get(domain, ()))
            contextual_bonus = 0.0
            combination_signals: list[str] = []
            if domain == "catalysis":
                contextual_bonus, combination_signals = _catalysis_context_bonus(text)
            elif domain == "corrosion":
                contextual_bonus, combination_signals = _corrosion_context_bonus(text)
            if combination_signals:
                focal = sorted(set([*focal, *combination_signals]))
            scores[domain] = max(0.0, score + contextual_bonus + 0.5 * len(focal) - 0.75 * len(incidental))
            matched_terms[domain] = hits
            focal_signals[domain] = focal
            incidental_signals[domain] = incidental

        best_domain = max(scores, key=scores.get)
        best = scores[best_domain]
        ordered = sorted(scores.values(), reverse=True)
        second = ordered[1] if len(ordered) > 1 else 0.0

        if best <= 0:
            raise ValueError("No supported materials-science domain could be identified from the supplied text.")

        breadth = min(best / 8.0, 1.0)
        margin = (best - second) / max(best, 1.0)
        confidence = round(max(0.35, min(0.99, 0.55 * breadth + 0.45 * margin)), 3)

        informatics_score, informatics_hits = _matched(text, MATERIALS_INFORMATICS_TERMS)
        ambiguity_reason = None
        selected_domain = best_domain
        if _has_materials_informatics_context(text, informatics_hits):
            selected_domain = "generic"
            ambiguity_reason = "materials_informatics_signals"
        elif best < _MIN_SCIENTIFIC_DOMAIN_SCORE and not focal_signals[best_domain]:
            selected_domain = "generic"
            ambiguity_reason = "weak_scientific_domain_evidence"
        elif margin < 0.25 and not focal_signals[best_domain]:
            selected_domain = "generic"
            ambiguity_reason = "conflicting_scientific_domain_evidence"

        if informatics_hits:
            matched_terms["generic"] = informatics_hits
            focal_signals["generic"] = []
            incidental_signals["generic"] = []
            scores["generic"] = informatics_score
        paper_types = (
            classify_battery_paper_types(text) if selected_domain == "batteries"
            else classify_catalysis_paper_types(text) if selected_domain == "catalysis"
            else classify_corrosion_paper_types(text) if selected_domain == "corrosion"
            else []
        )
        return DomainRoute(
            domain=selected_domain,
            confidence=confidence,
            scores=scores,
            matched_terms=matched_terms,
            paper_types=paper_types,
            focal_signals=focal_signals,
            incidental_signals=incidental_signals,
            ambiguity_reason=ambiguity_reason,
            scope_status=catalysis_scope_status(text) if selected_domain == "catalysis" else "supported",
        )
