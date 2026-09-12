from __future__ import annotations

from synthex_platform.core.archive import SynthexArchive


def to_optimade_structures(archive: SynthexArchive) -> list[dict]:
    """Best-effort OPTIMADE-like structure resources.

    Only emits records when the archive actually contains enough structural identity.
    Synthex-specific provenance remains under attributes._synthex.
    """
    resources = []
    for material in archive.materials:
        attrs = {
            "chemical_formula_descriptive": material.formula,
            "elements": material.elements or None,
            "nelements": len(material.elements) if material.elements else None,
            "_synthex": {
                "archive_id": archive.metadata.archive_id,
                "domain": archive.metadata.domain,
                "material_id": material.material_id,
                "phase": material.phase,
                "tags": material.tags,
            },
        }
        attrs = {k: v for k, v in attrs.items() if v is not None}
        resources.append({"id": material.material_id, "type": "structures", "attributes": attrs})
    return resources
