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
        "tensile test", "tensile testing", "yield strength", "ultimate tensile strength", "uts",
        "fracture strength", "elongation at break", "reduction of area", "young's modulus",
        "youngs modulus", "elastic modulus", "vickers hardness", "rockwell hardness",
        "brinell hardness", "nanoindentation", "creep test", "creep testing",
        "creep behavior", "minimum creep rate", "stress rupture", "stress-rupture",
        "rupture time", "time to rupture", "strain at rupture", "rupture life",
        "fatigue test", "fatigue testing", "fatigue life", "fatigue strength", "fatigue limit",
        "s-n curve", "sn curve", "cycles to failure", "stress amplitude", "strain amplitude",
        "crack growth rate", "paris law", "fracture toughness", "stress intensity factor",
        "j-integral", "ctod", "charpy impact", "stress-strain", "stress strain",
        "elastic constants", "elastic constant", "bulk modulus", "shear modulus",
        "poisson's ratio", "poisson ratio", "c11", "c12", "c44",
    ),
    "additive_manufacturing": (
        "additive manufacturing", "selective laser melting", "laser powder bed fusion",
        "powder bed fusion", "pbf-lb", "pbf-eb", "lpbf", "l-pbf", "slm", "dmls",
        "electron beam melting", "electron beam powder bed fusion", "ebm",
        "directed energy deposition", "ded", "laser metal deposition", "lmd",
        "wire arc additive manufacturing", "waam", "binder jetting",
    ),
    "photovoltaics": (
        "photovoltaic", "solar cell", "power conversion efficiency", "pce",
        "open-circuit voltage", "open circuit voltage", "voc",
        "short-circuit current", "short circuit current", "jsc", "fill factor", "eqe",
        "external quantum efficiency", "incident photon-to-current efficiency", "ipce",
        "am1.5g", "am 1.5 g", "solar simulator", "perovskite solar",
        "device architecture", "electron transport layer", "hole transport layer",
    ),
    "thermoelectrics": (
        "thermoelectric", "thermoelectrics", "seebeck coefficient", "thermopower",
        "figure of merit", "zt", "power factor", "lattice thermal conductivity",
        "electronic thermal conductivity", "wiedemann-franz", "hall carrier",
        "thermoelectric transport",
    ),
    "membranes": (
        "membrane", "membranes", "gas separation", "mixed-matrix membrane",
        "thin-film composite", "reverse osmosis", "nanofiltration", "ultrafiltration",
        "microfiltration", "pervaporation", "barrer", "gpu", "transmembrane pressure",
        "molecular weight cutoff", "mwco", "flux recovery ratio",
    ),
    "semiconductors": (
        "semiconductor", "semiconducting", "carrier mobility", "hall mobility",
        "hall coefficient", "carrier concentration", "sheet resistance",
        "electron concentration", "hole concentration", "effective mass",
        "band gap", "bandgap", "optical band gap", "work function",
        "electron affinity", "Fermi level", "dopant concentration",
        "thin-film transistor", "MOSFET", "Schottky", "ohmic contact",
    ),
    "biomaterials": (
        "biomaterial", "biocompatibility", "cell viability", "cell proliferation",
        "hemolysis", "osseointegration", "cytotoxicity", "bioactivity",
        "tissue engineering", "cell-laden scaffold", "bone scaffold", "wound dressing",
        "osteogenic", "antimicrobial hydrogel", "antibacterial scaffold",
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

MECHANICAL_PAPER_TYPE_TERMS: dict[str, tuple[str, ...]] = {
    "tensile_testing": (
        "tensile test", "tensile testing", "yield strength", "ultimate tensile strength",
        "elongation at break", "reduction of area", "stress-strain", "stress strain",
    ),
    "hardness_testing": (
        "vickers hardness", "rockwell hardness", "brinell hardness", "nanoindentation",
    ),
    "creep_stress_rupture": (
        "creep test", "creep testing", "creep behavior", "minimum creep rate",
        "stress rupture", "stress-rupture", "rupture time", "time to rupture",
        "strain at rupture", "rupture life",
    ),
    "fatigue_testing": (
        "fatigue test", "fatigue testing", "fatigue life", "s-n curve", "sn curve",
        "cycles to failure", "stress amplitude", "strain amplitude",
    ),
    "fracture_toughness": (
        "fracture toughness", "stress intensity factor", "j-integral", "ctod",
        "charpy impact", "crack growth rate", "paris law",
    ),
    "computational_mechanics": (
        "finite element", "constitutive model", "crystal plasticity", "model prediction",
        "machine learning prediction", "first-principles calculations", "first principles calculations",
        "density functional theory", "calculated elastic constants", "bulk modulus", "shear modulus",
    ),
    "review": ("review", "perspective", "overview"),
}

ADDITIVE_MANUFACTURING_PAPER_TYPE_TERMS: dict[str, tuple[str, ...]] = {
    "feedstock_characterization": (
        "powder feedstock", "particle size distribution", "d10", "d50", "d90",
        "powder morphology", "wire feedstock",
    ),
    "laser_powder_bed_fusion": (
        "laser powder bed fusion", "selective laser melting", "lpbf", "l-pbf", "slm", "dmls",
    ),
    "electron_beam_powder_bed_fusion": (
        "electron beam powder bed fusion", "electron beam melting", "pbf-eb", "ebm",
    ),
    "directed_energy_deposition": (
        "directed energy deposition", "laser metal deposition", "ded", "lmd",
    ),
    "wire_arc_additive_manufacturing": (
        "wire arc additive manufacturing", "waam",
    ),
    "binder_jetting": ("binder jetting", "binder-jetted"),
    "post_processing": (
        "stress relief", "hot isostatic pressing", "hip", "solution treatment", "post-processing",
    ),
    "quality_characterization": (
        "relative density", "porosity", "lack of fusion", "keyhole", "surface roughness",
        "melt pool", "grain size",
    ),
    "mechanical_characterization": (
        "tensile test", "yield strength", "ultimate tensile strength", "elongation",
        "hardness", "fatigue", "fracture toughness",
    ),
    "review": ("review", "perspective", "overview"),
}

PHOTOVOLTAICS_PAPER_TYPE_TERMS: dict[str, tuple[str, ...]] = {
    "device_fabrication": (
        "device fabrication", "solar cell fabrication", "spin coating", "blade coating",
        "thermal evaporation", "sputtering", "annealing", "encapsulation",
    ),
    "device_architecture": (
        "device architecture", "layer stack", "electron transport layer",
        "hole transport layer", "transparent electrode", "absorber layer",
    ),
    "photovoltaic_performance": (
        "power conversion efficiency", "pce", "open-circuit voltage", "voc",
        "short-circuit current density", "jsc", "fill factor", "solar simulator",
    ),
    "spectral_response": (
        "external quantum efficiency", "eqe", "incident photon-to-current efficiency", "ipce",
    ),
    "stability": (
        "stability", "degradation", "retained efficiency", "t80", "t90", "aging", "ageing",
    ),
    "computational_photovoltaics": (
        "density functional theory", "drift diffusion", "device simulation",
        "scaps", "wxamps", "calculated efficiency",
    ),
    "review": ("review", "perspective", "overview"),
}

THERMOELECTRICS_PAPER_TYPE_TERMS: dict[str, tuple[str, ...]] = {
    "thermoelectric_material_synthesis": (
        "thermoelectric material", "solid-state reaction", "spark plasma sintering",
        "hot pressing", "ball milling", "annealed", "densified",
    ),
    "electrical_transport": (
        "seebeck coefficient", "thermopower", "electrical conductivity",
        "electrical resistivity", "hall carrier", "carrier mobility",
    ),
    "thermal_transport": (
        "thermal conductivity", "lattice thermal conductivity",
        "electronic thermal conductivity", "thermal diffusivity", "laser flash",
    ),
    "thermoelectric_performance": (
        "figure of merit", "power factor", "zt", "average zt",
    ),
    "computational_thermoelectrics": (
        "boltzmann transport", "first-principles", "density functional theory",
        "phonon band structure", "grüneisen parameter",
    ),
    "review": ("review", "perspective", "overview"),
}

MEMBRANES_PAPER_TYPE_TERMS: dict[str, tuple[str, ...]] = {
    "membrane_fabrication": (
        "phase inversion", "nonsolvent induced phase separation", "solution casting",
        "interfacial polymerization", "spin coating", "dip coating", "kiss coating",
        "electrospinning", "crosslinking",
    ),
    "membrane_architecture": (
        "thin-film composite", "selective layer", "support layer", "porous support",
        "interlayer", "mixed-matrix membrane", "filler loading",
    ),
    "gas_separation": (
        "gas separation", "barrer", "gpu", "gas permeability", "gas permeance",
        "mixed-gas selectivity", "ideal selectivity",
    ),
    "liquid_separation": (
        "reverse osmosis", "nanofiltration", "desalination", "water permeance",
        "salt rejection", "solute rejection",
    ),
    "filtration": (
        "ultrafiltration", "microfiltration", "dead-end filtration", "cross-flow",
        "molecular weight cutoff", "mwco",
    ),
    "pervaporation": ("pervaporation", "separation factor", "permeation flux"),
    "fouling_stability": (
        "fouling", "antifouling", "flux recovery ratio", "relative flux reduction",
        "cleaning", "compaction", "plasticization", "physical aging",
    ),
    "computational_membranes": (
        "molecular dynamics", "gcmc", "transport modeling", "diffusion barrier",
        "simulated permeability", "predicted selectivity",
    ),
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
_MECHANICAL_TENSILE_METHOD_TERMS = ("tensile test", "tensile testing", "uniaxial tension")
_MECHANICAL_TENSILE_OUTPUT_TERMS = (
    "yield strength", "ultimate tensile strength", "uts", "elongation at break",
    "reduction of area", "young's modulus", "youngs modulus", "stress-strain", "stress strain",
)
_MECHANICAL_HARDNESS_METHOD_TERMS = ("vickers", "rockwell", "brinell", "nanoindentation")
_MECHANICAL_HARDNESS_OUTPUT_TERMS = ("hardness", "hv", "hra", "hrb", "hrc", "hb", "hbw")
_MECHANICAL_CREEP_METHOD_TERMS = (
    "creep test", "creep testing", "creep behavior", "stress rupture", "stress-rupture",
)
_MECHANICAL_CREEP_OUTPUT_TERMS = (
    "creep strain", "creep rate", "minimum creep rate", "rupture time",
    "time to rupture", "strain at rupture", "rupture life",
)
_MECHANICAL_FATIGUE_METHOD_TERMS = ("fatigue test", "fatigue testing", "s-n curve", "sn curve")
_MECHANICAL_FATIGUE_OUTPUT_TERMS = (
    "fatigue life", "fatigue strength", "fatigue limit", "cycles to failure",
    "stress amplitude", "strain amplitude", "crack growth rate",
)
_MECHANICAL_FRACTURE_METHOD_TERMS = (
    "fracture test", "compact tension", "three-point bend", "charpy impact",
)
_MECHANICAL_FRACTURE_OUTPUT_TERMS = (
    "fracture toughness", "stress intensity factor", "j-integral", "ctod", "impact energy",
)
_MECHANICAL_COMPUTATIONAL_METHOD_TERMS = (
    "density functional theory", "first-principles", "first principles", "castep",
)
_MECHANICAL_COMPUTATIONAL_OUTPUT_TERMS = (
    "elastic constants", "elastic constant", "c11", "c12", "c44",
    "bulk modulus", "shear modulus", "young's modulus", "poisson's ratio",
)
_AM_PROCESS_TERMS = (
    "additive manufacturing", "laser powder bed fusion", "selective laser melting",
    "powder bed fusion", "pbf-lb", "pbf-eb", "lpbf", "l-pbf", "slm", "dmls",
    "electron beam melting", "electron beam powder bed fusion", "ebm",
    "directed energy deposition", "ded", "laser metal deposition", "lmd",
    "wire arc additive manufacturing", "waam", "binder jetting",
)
_AM_PARAMETER_TERMS = (
    "laser power", "beam power", "scan speed", "scanning speed", "hatch spacing",
    "hatch distance", "layer thickness", "spot size", "beam diameter", "powder feed rate",
    "wire feed rate", "scan strategy", "build orientation", "preheat temperature",
    "chamber oxygen", "shielding gas", "energy density",
)
_AM_OUTPUT_TERMS = (
    "relative density", "porosity", "defect fraction", "lack of fusion", "keyhole porosity",
    "surface roughness", "melt pool width", "melt pool depth", "grain size", "build rate",
    "yield strength", "ultimate tensile strength", "elongation", "hardness", "fatigue",
)
_PV_DEVICE_TERMS = (
    "photovoltaic", "solar cell", "solar cells", "photovoltaic device",
    "photovoltaic module", "perovskite solar", "organic solar",
)
_PV_PERFORMANCE_TERMS = (
    "power conversion efficiency", "pce", "open-circuit voltage", "open circuit voltage",
    "short-circuit current", "short circuit current", "fill factor", "voc", "jsc",
)
_PV_SPECTRAL_TERMS = (
    "external quantum efficiency", "incident photon-to-current efficiency", "eqe", "ipce",
)
_PV_WAVELENGTH_TERMS = ("wavelength", "nm", "spectral response")
_PV_STANDARD_ILLUMINATION_TERMS = ("am1.5g", "am 1.5 g", "am 1.5g", "solar simulator")
_TE_IDENTITY_TERMS = ("thermoelectric", "thermoelectrics", "seebeck coefficient", "thermopower")
_TE_TRANSPORT_TERMS = (
    "electrical conductivity", "electrical resistivity", "thermal conductivity",
    "lattice thermal conductivity", "electronic thermal conductivity", "carrier mobility",
)
_TE_PERFORMANCE_TERMS = ("figure of merit", "power factor", "zt")
_TE_TEMPERATURE_TERMS = ("temperature-dependent", "as a function of temperature", "temperature range")
_MEMBRANE_IDENTITY_TERMS = (
    "membrane", "membranes", "mixed-matrix membrane", "thin-film composite",
    "reverse osmosis", "nanofiltration", "ultrafiltration", "microfiltration", "pervaporation",
)
_MEMBRANE_GAS_OUTPUT_TERMS = (
    "gas permeability", "gas permeance", "barrer", "gpu", "mixed-gas selectivity",
    "ideal selectivity", "gas separation",
)
_MEMBRANE_LIQUID_OUTPUT_TERMS = (
    "water flux", "liquid flux", "water permeance", "salt rejection", "solute rejection",
    "retention", "transmembrane pressure", "molecular weight cutoff", "mwco",
)
_MEMBRANE_STABILITY_TERMS = (
    "flux recovery ratio", "relative flux reduction", "antifouling", "membrane fouling",
    "plasticization pressure", "permeability retention",
)
_SEMICONDUCTOR_IDENTITY_TERMS = (
    "semiconductor", "semiconducting", "zno", "sno2", "inn", "alxin",
    "thin-film transistor", "mosfet", "fet", "schottky",
)
_SEMICONDUCTOR_TRANSPORT_TERMS = (
    "hall mobility", "hall coefficient", "carrier concentration", "electron concentration",
    "hole concentration", "sheet resistance", "carrier mobility",
)
_SEMICONDUCTOR_ELECTRONIC_TERMS = (
    "optical band gap", "electronic band gap", "band gap", "bandgap",
    "work function", "electron affinity", "photoluminescence",
)
_BIO_SPECIMEN_TERMS = (
    "biomaterial", "material", "scaffold", "implant", "hydrogel", "wound dressing",
    "tissue-engineered", "tissue engineering", "bioprinted", "bio-printed",
)
_BIO_RESPONSE_TERMS = (
    "cell viability", "cell proliferation", "cell adhesion", "cytotoxicity",
    "biocompatibility", "hemolysis", "osteogenic", "mineralization",
    "alp activity", "antibacterial", "antimicrobial", "inhibition zone",
)
_EXPLICIT_REVIEW_SELF_DESCRIPTION = re.compile(
    r"(?:this paper presents a comprehensive review|this review (?:has focused|summarizes|reviews)|"
    r"this work aims to present\s+an overview)",
    re.IGNORECASE,
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
    "we tested", "tests were conducted", "was measured", "were measured",
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


def classify_mechanical_paper_types(text: str) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for paper_type, terms in MECHANICAL_PAPER_TYPE_TERMS.items():
        score, _ = _matched(text, terms)
        if score > 0:
            ranked.append((score, paper_type))
    ranked.sort(reverse=True)
    return [name for score, name in ranked if score >= 1.0][:6]


def classify_additive_manufacturing_paper_types(text: str) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for paper_type, terms in ADDITIVE_MANUFACTURING_PAPER_TYPE_TERMS.items():
        score, _ = _matched(text, terms)
        if score > 0:
            ranked.append((score, paper_type))
    ranked.sort(reverse=True)
    return [name for score, name in ranked if score >= 1.0][:8]


def classify_photovoltaics_paper_types(text: str) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for paper_type, terms in PHOTOVOLTAICS_PAPER_TYPE_TERMS.items():
        score, _ = _matched(text, terms)
        if score > 0:
            ranked.append((score, paper_type))
    ranked.sort(reverse=True)
    return [name for score, name in ranked if score >= 1.0][:7]


def classify_thermoelectrics_paper_types(text: str) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for paper_type, terms in THERMOELECTRICS_PAPER_TYPE_TERMS.items():
        score, _ = _matched(text, terms)
        if score > 0:
            ranked.append((score, paper_type))
    ranked.sort(reverse=True)
    return [name for score, name in ranked if score >= 1.0][:6]


def classify_membranes_paper_types(text: str) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for paper_type, terms in MEMBRANES_PAPER_TYPE_TERMS.items():
        if paper_type == "review" and not _is_explicit_review_lead(text):
            continue
        if paper_type == "pervaporation" and not _count_term(text, "pervaporation"):
            continue
        score, _ = _matched(text, terms)
        if score > 0:
            ranked.append((score, paper_type))
    ranked.sort(reverse=True)
    return [name for score, name in ranked if score >= 1.0][:7]


def classify_semiconductors_paper_types(text: str) -> list[str]:
    terms = {
        "semiconductor_growth": ("growth", "deposition", "sputtering", "chemical vapor deposition", "atomic layer deposition"),
        "doping_and_processing": ("doping", "dopant", "annealing", "tempering"),
        "electrical_transport": _SEMICONDUCTOR_TRANSPORT_TERMS,
        "optical_characterization": _SEMICONDUCTOR_ELECTRONIC_TERMS,
        "device_characterization": ("mosfet", "fet", "threshold voltage", "contact resistance", "subthreshold swing"),
        "computational_electronics": ("band structure", "density functional theory", "gw", "hybrid functional"),
    }
    ranked = [(score, name) for name, group in terms.items() for score, _ in [_matched(text, group)] if score >= 1.0]
    ranked.sort(reverse=True)
    return [name for _, name in ranked[:6]]


def classify_biomaterials_paper_types(text: str) -> list[str]:
    groups = {
        "biomaterial_fabrication": ("3d printing", "bioprinting", "crosslinking", "electrospinning", "freeze drying"),
        "cytocompatibility": ("cell viability", "cytotoxicity", "cell proliferation", "live/dead", "mtt assay"),
        "hemocompatibility": ("hemolysis", "platelet adhesion", "coagulation"),
        "bioactivity": ("osteogenic", "mineralization", "apatite", "alp activity"),
        "antimicrobial": ("inhibition zone", "antimicrobial", "antibacterial", "colony forming"),
        "swelling_degradation": ("swelling", "mass loss", "biodegradation", "water uptake"),
        "scaffold_mechanics": ("compressive modulus", "compressive strength", "tensile strength"),
        "computational_biomaterials": ("molecular dynamics", "molecular docking", "scaffold simulation"),
    }
    ranked = [(score, name) for name, terms in groups.items() for score, _ in [_matched(text, terms)] if score >= 1.0]
    ranked.sort(reverse=True)
    return [name for _, name in ranked[:6]]


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


def _mechanical_context_bonus(text: str) -> tuple[float, list[str]]:
    groups = (
        ("tensile_context", _MECHANICAL_TENSILE_METHOD_TERMS, _MECHANICAL_TENSILE_OUTPUT_TERMS),
        ("hardness_context", _MECHANICAL_HARDNESS_METHOD_TERMS, _MECHANICAL_HARDNESS_OUTPUT_TERMS),
        ("creep_context", _MECHANICAL_CREEP_METHOD_TERMS, _MECHANICAL_CREEP_OUTPUT_TERMS),
        ("fatigue_context", _MECHANICAL_FATIGUE_METHOD_TERMS, _MECHANICAL_FATIGUE_OUTPUT_TERMS),
        ("fracture_context", _MECHANICAL_FRACTURE_METHOD_TERMS, _MECHANICAL_FRACTURE_OUTPUT_TERMS),
        ("computational_mechanics_context", _MECHANICAL_COMPUTATIONAL_METHOD_TERMS, _MECHANICAL_COMPUTATIONAL_OUTPUT_TERMS),
    )
    signals: list[str] = []
    bonus = 0.0
    for signal, method_terms, output_terms in groups:
        method_score, _ = _matched(text, method_terms)
        output_score, _ = _matched(text, output_terms)
        if method_score and output_score:
            bonus += 3.5
            signals.append(signal)
    return min(bonus, 7.0), signals


def _additive_manufacturing_context_bonus(text: str) -> tuple[float, list[str]]:
    process_score, _ = _matched(text, _AM_PROCESS_TERMS)
    parameter_score, _ = _matched(text, _AM_PARAMETER_TERMS)
    output_score, _ = _matched(text, _AM_OUTPUT_TERMS)
    if process_score and parameter_score and output_score:
        return 4.0, ["am_process_parameter_output_context"]
    if process_score and (parameter_score or output_score):
        return 3.0, ["am_process_scientific_context"]
    return 0.0, []


def _photovoltaics_context_bonus(text: str) -> tuple[float, list[str]]:
    device_score, _ = _matched(text, _PV_DEVICE_TERMS)
    performance_score, performance_hits = _matched(text, _PV_PERFORMANCE_TERMS)
    spectral_score, _ = _matched(text, _PV_SPECTRAL_TERMS)
    wavelength_score, _ = _matched(text, _PV_WAVELENGTH_TERMS)
    illumination_score, _ = _matched(text, _PV_STANDARD_ILLUMINATION_TERMS)
    photocatalysis_score, _ = _matched(text, _CATALYSIS_DEFERRED_TERMS[:2])
    signals: list[str] = []
    bonus = 0.0
    if photocatalysis_score and not device_score:
        # EQE/IPCE and wavelength also occur in photocatalysis. Without an explicit
        # photovoltaic device, those spectral words cannot establish PV ownership.
        return 0.0, []
    if device_score and performance_score:
        bonus = max(bonus, 4.0)
        signals.append("pv_device_performance_context")
    metric_triplet = {"voc", "jsc", "fill factor"}.issubset(set(performance_hits))
    if metric_triplet:
        bonus = max(bonus, 4.5)
        signals.append("pv_voc_jsc_fill_factor_context")
    if spectral_score and wavelength_score:
        bonus = max(bonus, 3.5)
        signals.append("pv_spectral_wavelength_context")
    if illumination_score and (device_score or performance_score):
        bonus = max(bonus, 4.0)
        signals.append("pv_standard_illumination_device_context")
    return bonus, signals


def _thermoelectrics_context_bonus(text: str) -> tuple[float, list[str]]:
    identity_score, _ = _matched(text, _TE_IDENTITY_TERMS)
    transport_score, _ = _matched(text, _TE_TRANSPORT_TERMS)
    performance_score, _ = _matched(text, _TE_PERFORMANCE_TERMS)
    temperature_score, _ = _matched(text, _TE_TEMPERATURE_TERMS)
    signals: list[str] = []
    bonus = 0.0
    if identity_score and transport_score and performance_score:
        bonus = max(bonus, 4.5)
        signals.append("te_transport_performance_context")
    if identity_score and temperature_score and (transport_score or performance_score):
        bonus = max(bonus, 4.0)
        signals.append("te_temperature_series_context")
    return bonus, signals


def _membranes_context_bonus(text: str) -> tuple[float, list[str]]:
    identity_score, _ = _matched(text, _MEMBRANE_IDENTITY_TERMS)
    gas_score, _ = _matched(text, _MEMBRANE_GAS_OUTPUT_TERMS)
    liquid_score, _ = _matched(text, _MEMBRANE_LIQUID_OUTPUT_TERMS)
    stability_score, _ = _matched(text, _MEMBRANE_STABILITY_TERMS)
    explicit_gas_pair = bool(re.search(
        r"\b(?:co2|h2|o2|n2|ch4|he|c2h4)\s*/\s*(?:co2|h2|o2|n2|ch4|he|c2h4)\b",
        text, flags=re.IGNORECASE,
    ))
    signals: list[str] = []
    bonus = 0.0
    if identity_score and gas_score and ("gas separation" in text.casefold() or explicit_gas_pair):
        bonus = max(bonus, 4.5)
        signals.append("membrane_gas_transport_context")
    if identity_score and liquid_score and any(
        term in text.casefold()
        for term in ("reverse osmosis", "nanofiltration", "ultrafiltration", "microfiltration", "desalination", "filtration")
    ):
        bonus = max(bonus, 4.5)
        signals.append("membrane_liquid_separation_context")
    if "pervaporation" in text.casefold() and (
        "separation factor" in text.casefold() or "permeation flux" in text.casefold()
    ):
        bonus = max(bonus, 4.5)
        signals.append("membrane_pervaporation_context")
    if identity_score and stability_score:
        bonus = max(bonus, 4.0)
        signals.append("membrane_fouling_or_stability_context")
    return bonus, signals


def _semiconductors_context_bonus(text: str) -> tuple[float, list[str]]:
    lead = text[:14000]
    identity, _ = _matched(lead, _SEMICONDUCTOR_IDENTITY_TERMS)
    transport, _ = _matched(lead, _SEMICONDUCTOR_TRANSPORT_TERMS)
    electronic, _ = _matched(lead, _SEMICONDUCTOR_ELECTRONIC_TERMS)
    device, _ = _matched(lead, ("fet", "mosfet", "thin-film transistor"))
    signals: list[str] = []
    if identity and transport >= 2:
        signals.append("semiconductor_specimen_transport_context")
    if identity and electronic and ("film" in lead.casefold() or "wafer" in lead.casefold()):
        signals.append("semiconductor_film_electronic_context")
    if device and ("threshold voltage" in lead.casefold() or "carrier mobility" in lead.casefold()):
        signals.append("semiconductor_device_metric_context")
    if "hall coefficient" in lead.casefold() and "carrier concentration" in lead.casefold():
        signals.append("semiconductor_hall_transport_context")
    return (5.0 if signals else 0.0), signals


def _biomaterials_context_bonus(text: str) -> tuple[float, list[str]]:
    lead = text[:14000]
    specimen, _ = _matched(lead, _BIO_SPECIMEN_TERMS)
    response, _ = _matched(lead, _BIO_RESPONSE_TERMS)
    if specimen and response:
        return 7.0, ["biomaterial_specimen_biological_response_context"]
    return 0.0, []


def _is_explicit_review_lead(text: str) -> bool:
    """Detect the two review signals used by the ownership guards in the lead pages."""
    lead = text[:20000]
    has_publisher_label = any(
        line.strip().casefold() == "review" for line in lead.splitlines()
    )
    return has_publisher_label and bool(_EXPLICIT_REVIEW_SELF_DESCRIPTION.search(lead))


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
            elif domain == "mechanical":
                contextual_bonus, combination_signals = _mechanical_context_bonus(text)
            elif domain == "additive_manufacturing":
                contextual_bonus, combination_signals = _additive_manufacturing_context_bonus(text)
            elif domain == "photovoltaics":
                contextual_bonus, combination_signals = _photovoltaics_context_bonus(text)
            elif domain == "thermoelectrics":
                contextual_bonus, combination_signals = _thermoelectrics_context_bonus(text)
            elif domain == "membranes":
                contextual_bonus, combination_signals = _membranes_context_bonus(text)
            elif domain == "semiconductors":
                contextual_bonus, combination_signals = _semiconductors_context_bonus(text)
            elif domain == "biomaterials":
                contextual_bonus, combination_signals = _biomaterials_context_bonus(text)
            if combination_signals:
                focal = sorted(set([*focal, *combination_signals]))
            scores[domain] = max(0.0, score + contextual_bonus + 0.5 * len(focal) - 0.75 * len(incidental))
            matched_terms[domain] = hits
            focal_signals[domain] = focal
            incidental_signals[domain] = incidental

        best_domain = max(scores, key=scores.get)
        bio_has_focal_context = "biomaterial_specimen_biological_response_context" in focal_signals.get("biomaterials", [])
        if best_domain == "biomaterials" and not bio_has_focal_context:
            eligible = {domain: score for domain, score in scores.items() if domain != "biomaterials"}
            best_domain = max(eligible, key=eligible.get)
        pv_has_focal_context = bool(
            set(focal_signals.get("photovoltaics", []))
            & {
                "pv_device_performance_context",
                "pv_voc_jsc_fill_factor_context",
                "pv_spectral_wavelength_context",
                "pv_standard_illumination_device_context",
            }
        )
        if best_domain == "photovoltaics" and not pv_has_focal_context:
            # Generic efficiency/current/voltage/layer language is shared by batteries,
            # semiconductors, catalysis, and thin-film processing. PV owns the route only
            # when a device-performance, metric-triplet, spectral, or standard-illumination
            # combination is present.
            eligible = {domain: score for domain, score in scores.items() if domain != "photovoltaics"}
            best_domain = max(eligible, key=eligible.get)
        membrane_has_focal_context = bool(
            set(focal_signals.get("membranes", []))
            & {
                "membrane_gas_transport_context",
                "membrane_liquid_separation_context",
                "membrane_pervaporation_context",
                "membrane_fouling_or_stability_context",
            }
        )
        if best_domain == "membranes" and not membrane_has_focal_context:
            # Permeability, selectivity, flux, filtering and layers are shared with
            # biology, batteries, coatings and porous-material characterization.
            eligible = {domain: score for domain, score in scores.items() if domain != "membranes"}
            best_domain = max(eligible, key=eligible.get)
        semi_has_focal_context = any(
            signal.startswith("semiconductor_")
            for signal in focal_signals.get("semiconductors", [])
        )
        if best_domain == "semiconductors" and not semi_has_focal_context:
            # Band gap, film, conductivity and mobility alone are cross-domain.
            eligible = {domain: score for domain, score in scores.items() if domain != "semiconductors"}
            best_domain = max(eligible, key=eligible.get)
        if best_domain == "semiconductors" and pv_has_focal_context:
            best_domain = "photovoltaics"
        te_focal = set(focal_signals.get("thermoelectrics", []))
        if best_domain == "semiconductors" and (
            "te_transport_performance_context" in te_focal
            or "te_temperature_transport_context" in te_focal
        ) and scores.get("thermoelectrics", 0) >= scores["semiconductors"] - 2:
            best_domain = "thermoelectrics"
        am_has_focal_process_chain = (
            "am_process_parameter_output_context" in focal_signals.get("additive_manufacturing", [])
            and len(matched_terms.get("additive_manufacturing", [])) >= 2
            and scores.get("additive_manufacturing", 0.0) >= 8.0
        )
        if (
            best_domain == "mechanical"
            and am_has_focal_process_chain
            and not _is_explicit_review_lead(text)
        ):
            # Mechanical characterization is frequently an output of a focal AM build
            # study.  A complete AM process/parameter/output chain therefore owns the
            # primary-research route even when repeated tensile vocabulary has a higher
            # raw count. Explicit reviews retain their strongest native domain.
            best_domain = "additive_manufacturing"
        best = scores[best_domain]
        second = max((score for domain, score in scores.items() if domain != best_domain), default=0.0)

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
            else classify_mechanical_paper_types(text) if selected_domain == "mechanical"
            else classify_additive_manufacturing_paper_types(text) if selected_domain == "additive_manufacturing"
            else classify_photovoltaics_paper_types(text) if selected_domain == "photovoltaics"
            else classify_thermoelectrics_paper_types(text) if selected_domain == "thermoelectrics"
            else classify_membranes_paper_types(text) if selected_domain == "membranes"
            else classify_semiconductors_paper_types(text) if selected_domain == "semiconductors"
            else classify_biomaterials_paper_types(text) if selected_domain == "biomaterials"
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
