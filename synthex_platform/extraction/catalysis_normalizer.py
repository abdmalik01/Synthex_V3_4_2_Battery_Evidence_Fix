"""Conservative normalization and comparability helpers for Catalysis V1.

This module creates metadata only. It performs no potential conversion and no
cross-normalization between scientific denominator bases.
"""

from __future__ import annotations

from .catalysis_models import ElectrochemicalPotential, NormalizationBasis


def normalization_key(basis: NormalizationBasis | None) -> str | None:
    if basis is None or basis.kind == "unknown":
        return None
    discriminator = basis.material_ref or basis.reported_basis or ""
    return f"{basis.kind}:{discriminator}"


def comparability_status(left: NormalizationBasis | None, right: NormalizationBasis | None = None) -> str:
    if left is None or left.kind == "unknown":
        return "unknown_basis"
    if right is None:
        return left.comparison_status if left.comparison_status != "unknown_basis" else "comparable"
    if right.kind == "unknown":
        return "unknown_basis"
    return "comparable" if normalization_key(left) == normalization_key(right) else "not_comparable"


def potential_comparability_key(potential: ElectrochemicalPotential | None) -> str | None:
    if potential is None or potential.reported_reference == "unknown":
        return None
    return f"reported:{potential.reported_reference}:{potential.reported_reference_text or ''}"


def potential_conversion_warning(potential: ElectrochemicalPotential | None) -> str | None:
    """Explain conservative non-conversion without deriving a value."""
    if potential is None or potential.converted_potential is not None:
        return None
    if potential.reported_reference in {"Ag/AgCl", "SCE", "Hg/HgO", "Hg/Hg2SO4"}:
        return "potential_not_converted_incomplete_reference_conditions"
    return None
