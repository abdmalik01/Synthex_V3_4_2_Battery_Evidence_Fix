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


DOMAIN_TERMS: dict[str, tuple[str, ...]] = {
    "batteries": (
        "lithium-ion", "li-ion", "battery", "batteries", "cathode", "anode",
        "electrolyte", "charge-discharge", "charge discharge", "coulombic",
        "capacity retention", "c-rate", "state of health", "state-of-health",
        "constant current", "constant voltage", "electrochemical impedance spectroscopy",
    ),
    "gas_sensing": (
        "gas sensor", "gas sensing", "chemiresistive", "target gas", "response time",
        "recovery time", "selectivity", "ppm", "ppb", "sensor response",
    ),
    "catalysis": (
        "catalyst", "catalysis", "electrocatalysis", "overpotential", "tafel slope",
        "faradaic efficiency", "turnover frequency", "oer", "her", "orr",
    ),
    "corrosion": (
        "corrosion", "corrosion rate", "pitting", "icorr", "ecorr", "polarization resistance",
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


def _count_term(text: str, term: str) -> int:
    # Phrase-aware count. Short acronyms receive word boundaries to reduce accidental matches.
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
            # Cap repetition so one repeated term cannot overwhelm all other evidence.
            score += 1.0 + min(n - 1, 4) * 0.25
    return score, hits


def classify_battery_paper_types(text: str) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for paper_type, terms in BATTERY_PAPER_TYPE_TERMS.items():
        score, _ = _matched(text, terms)
        if score > 0:
            ranked.append((score, paper_type))
    ranked.sort(reverse=True)
    # Multi-label by design; keep substantive categories and avoid an unbounded tag list.
    return [name for score, name in ranked if score >= 1.0][:5]


class DomainRouter:
    """Fast, deterministic first-pass domain router.

    The router deliberately does not require Gemini. This keeps routing available offline and
    prevents spending an LLM request before we know which scientific schema/prompt to use.
    Domain-specific extractors may perform a second-stage check later.
    """

    def __init__(self, registry: DomainRegistry | None = None):
        self.registry = registry or DomainRegistry()

    def route_text(self, text: str) -> DomainRoute:
        if not text or not text.strip():
            raise ValueError("Cannot route empty text.")

        available = {d["slug"] for d in self.registry.list_domains()}
        scores: dict[str, float] = {}
        matched_terms: dict[str, list[str]] = {}

        for domain in sorted(available):
            score, hits = _matched(text, DOMAIN_TERMS.get(domain, ()))
            scores[domain] = score
            matched_terms[domain] = hits

        best_domain = max(scores, key=scores.get)
        best = scores[best_domain]
        ordered = sorted(scores.values(), reverse=True)
        second = ordered[1] if len(ordered) > 1 else 0.0

        if best <= 0:
            # No evidence: semiconductors is NOT a safe default. Fail loudly so the UI can ask.
            raise ValueError("No supported materials-science domain could be identified from the supplied text.")

        # Confidence combines evidence breadth and separation from the runner-up; it is a routing
        # confidence, not a scientific extraction confidence.
        breadth = min(best / 8.0, 1.0)
        margin = (best - second) / max(best, 1.0)
        confidence = round(max(0.35, min(0.99, 0.55 * breadth + 0.45 * margin)), 3)

        paper_types = classify_battery_paper_types(text) if best_domain == "batteries" else []
        return DomainRoute(
            domain=best_domain,
            confidence=confidence,
            scores=scores,
            matched_terms=matched_terms,
            paper_types=paper_types,
        )
