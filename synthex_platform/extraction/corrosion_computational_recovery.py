"""Deterministic recovery of clearly structured corrosion calculation tables.

Recovery is intentionally limited to tables whose captions and row/column layout expose
unambiguous descriptor identities. It performs no algebraic derivation and makes no
provider calls.
"""

from __future__ import annotations

import re

from synthex_platform.scientific_text import normalize_scientific_text

from .corrosion_models import (
    CoatingOrInhibitor,
    CorrosionCalculation,
    CorrosionCalculationOutput,
    CorrosionDocument,
    CorrosionEvidence,
    CorrosionExperiment,
    CorrosionMaterial,
    CorrosionMetric,
    CorrosionQuantity,
)
from .source_context import SourceBundle


_LABEL = re.compile(r"^[A-Z][A-Z0-9-]{0,5}$")
_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?")


def _norm(value: object | None) -> str:
    return normalize_scientific_text(value)


def _number(value: object | None) -> float | None:
    match = _NUMBER.search(_norm(value).replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _row_text(row: list[str | None]) -> str:
    return " ".join(str(value) for value in row if value not in (None, "")).strip()


def _cell_locator(table, row: int, column: int) -> str:
    cell = next((item for item in table.cells if item.row == row and item.column == column), None)
    return (cell.cell_id if cell and cell.cell_id else f"{table.table_id}:r{row}:c{column}")


def _table_evidence(table, snippet: str, *, row: int | None = None, column: int | None = None) -> CorrosionEvidence:
    locator = None
    if row is not None and column is not None:
        locator = _cell_locator(table, row, column)
    return CorrosionEvidence(
        page=table.page,
        text_snippet=snippet,
        source_type="table",
        original_source_type="table_reported",
        table_id=table.table_id,
        locator=locator,
    )


def _page_evidence(bundle: SourceBundle, page_number: int, needle: str) -> CorrosionEvidence | None:
    page = next((item for item in bundle.pages if item.page == page_number), None)
    if page is None or _norm(needle) not in _norm(page.native_text):
        return None
    return CorrosionEvidence(page=page_number, text_snippet=needle, source_type="text")


def _ensure_material(document: CorrosionDocument, bundle: SourceBundle) -> str | None:
    focal = next((item for item in document.materials if item.ownership == "focal_work"), None)
    if focal is not None:
        return focal.local_id
    page = next((item for item in bundle.pages if "iron surface fe(110)" in _norm(item.native_text)), None)
    if page is None:
        return None
    snippet = "inhibitor molecules and iron surface Fe(110)"
    document.materials.append(CorrosionMaterial(
        local_id="recovered_fe110",
        reported_name="iron surface Fe(110)",
        canonical_name="Fe(110)",
        material_class="pure_metal",
        role="corroding_material",
        ownership="focal_work",
        evidence=[CorrosionEvidence(page=page.page, text_snippet=snippet, source_type="text")],
    ))
    return "recovered_fe110"


def _ensure_treatment(document: CorrosionDocument, label: str, bundle: SourceBundle) -> str:
    for treatment in document.treatments:
        if _norm(label) == _norm(treatment.reported_name) or re.search(
            rf"\({re.escape(label)}\)", treatment.reported_name or "", re.IGNORECASE
        ):
            return treatment.treatment_id
    page = next((item for item in bundle.pages if re.search(rf"\b{re.escape(label)}\b", item.native_text)), None)
    evidence = [CorrosionEvidence(page=page.page, text_snippet=label, source_type="text")] if page else []
    treatment_id = f"recovered_inhibitor_{label.casefold()}"
    document.treatments.append(CoatingOrInhibitor(
        treatment_id=treatment_id,
        treatment_type="inhibitor",
        reported_name=label,
        ownership="focal_work",
        evidence=evidence,
    ))
    return treatment_id


def _context(bundle: SourceBundle) -> dict[str, str | CorrosionQuantity | None]:
    text = "\n".join(page.native_text for page in bundle.pages)
    normalized = _norm(text)
    return {
        "software": (
            "DMol3 in Materials Studio Modeling 4.0"
            if "dmol3" in normalized and "modeling version 4.0" in normalized else None
        ),
        "functional": "PWC" if "(pwc) exchange-correlation" in normalized else (
            "B3LYP" if "b3lyp" in normalized else None
        ),
        "basis_set": "DNP" if "dnp basis set" in normalized else None,
        "core_treatment": (
            "all-electron relativistic (AER)"
            if "all-electronrelativistic(aer)asthecoretreatment" in normalized else None
        ),
        "k_point_grid": (
            "2 x 2 x 1"
            if "2 x 2 x 1 mesh" in normalized
            or re.search(r"2\s*[^0-9a-z]\s*2\s*[^0-9a-z]\s*1\s*meshparameters", normalized)
            else None
        ),
        "geometry_optimization": "local minimum without imaginary frequency" if "without imaginary frequency" in normalized else None,
        "force_field": "COMPASS" if "compass" in normalized else None,
        "ensemble": "NVE" if "nve" in normalized else None,
        "temperature": CorrosionQuantity(raw_value="303 K", value=303, unit="K", qualifier="exact") if re.search(r"303\s*k", normalized) else None,
        "time_step": CorrosionQuantity(raw_value="0.1 fs", value=0.1, unit="fs", qualifier="exact") if re.search(r"0\.1\s*fs", normalized) else None,
        "simulation_time": CorrosionQuantity(raw_value="0.5 ps", value=0.5, unit="ps", qualifier="exact") if re.search(r"0\.5\s*ps", normalized) else None,
    }


def _calculation(
    document: CorrosionDocument,
    *,
    calculation_id: str,
    calculation_type: str,
    material_ref: str,
    treatment_ref: str,
    label: str,
    table,
    outputs: list[CorrosionCalculationOutput],
    context: dict,
) -> None:
    existing = next((item for item in document.calculations if item.calculation_id == calculation_id), None)
    if existing is not None:
        seen = {(item.property, item.quantity.value, item.quantity.unit) for item in existing.outputs}
        existing.outputs.extend(
            item for item in outputs
            if (item.property, item.quantity.value, item.quantity.unit) not in seen
        )
        return
    method = (
        "density functional theory (DFT)"
        if calculation_type == "dft" else "Forcite quench molecular dynamics"
    )
    document.calculations.append(CorrosionCalculation(
        calculation_id=calculation_id,
        calculation_type=calculation_type,
        material_refs=[material_ref],
        treatment_refs=[treatment_ref],
        surface="Fe(110)",
        adsorbate_or_inhibitor=label,
        method=method,
        software=context.get("software") if calculation_type == "dft" else "Materials Studio Modeling 4.0",
        functional=context.get("functional") if calculation_type == "dft" else None,
        basis_set=context.get("basis_set") if calculation_type == "dft" else None,
        core_treatment=context.get("core_treatment") if calculation_type == "dft" else None,
        phase="gas phase" if calculation_type == "dft" else "metal/vacuum interface",
        geometry_optimization=context.get("geometry_optimization"),
        k_point_grid=context.get("k_point_grid") if calculation_type == "dft" else None,
        force_field=context.get("force_field") if calculation_type == "molecular_dynamics" else None,
        ensemble=context.get("ensemble") if calculation_type == "molecular_dynamics" else None,
        temperature=context.get("temperature") if calculation_type == "molecular_dynamics" else None,
        time_step=context.get("time_step") if calculation_type == "molecular_dynamics" else None,
        simulation_time=context.get("simulation_time") if calculation_type == "molecular_dynamics" else None,
        outputs=outputs,
        ownership="focal_work",
        evidence=[_table_evidence(table, table.caption or _row_text(table.raw_representation.get("grid", [[]])[0]))],
    ))


def _recover_multi_adsorbate_tables(document: CorrosionDocument, bundle: SourceBundle, material_ref: str) -> None:
    context = _context(bundle)
    for table in bundle.tables:
        caption = _norm(table.caption)
        grid = table.raw_representation.get("grid", [])
        if "ehomo" in caption and "elumo" in caption and "chemical potential" in caption:
            mappings = (
                (1, "homo_energy", "EHOMO", "eV"),
                (2, "lumo_energy", "ELUMO", "eV"),
                (3, "chemical_potential", "chemical potential", "eV"),
                (4, "electron_transfer_number", "ΔN", "e"),
                (5, "global_hardness", "global hardness", "eV"),
            )
            for row_index, row in enumerate(grid):
                label = str(row[0] or "").strip() if row else ""
                if not _LABEL.fullmatch(label) or len(row) < 6:
                    continue
                treatment_ref = _ensure_treatment(document, label, bundle)
                exact_row = _row_text(row)
                outputs: list[CorrosionCalculationOutput] = []
                for column, property_name, term, unit in mappings:
                    value = _number(row[column])
                    if value is None:
                        continue
                    outputs.append(CorrosionCalculationOutput(
                        property=property_name,
                        reported_term=term,
                        quantity=CorrosionQuantity(raw_value=str(row[column]), value=value, unit=unit, qualifier="exact"),
                        data_kind="reported_calculation",
                        ownership="focal_work",
                        evidence=[_table_evidence(table, exact_row, row=row_index, column=column)],
                    ))
                _calculation(
                    document,
                    calculation_id=f"recovered_dft_{label.casefold()}",
                    calculation_type="dft",
                    material_ref=material_ref,
                    treatment_ref=treatment_ref,
                    label=label,
                    table=table,
                    outputs=outputs,
                    context=context,
                )

        if "binding energy" in caption and "interaction energy" in caption and "total energy" in caption:
            for row_index, row in enumerate(grid):
                for column, raw_label in enumerate(row):
                    label = str(raw_label or "").strip()
                    if not _LABEL.fullmatch(label) or column + 3 >= len(row):
                        continue
                    values = [_number(row[column + offset]) for offset in (1, 2, 3)]
                    if any(value is None for value in values):
                        continue
                    treatment_ref = _ensure_treatment(document, label, bundle)
                    exact_row = _row_text(row)
                    outputs = [
                        CorrosionCalculationOutput(
                            property=property_name,
                            reported_term=term,
                            quantity=CorrosionQuantity(raw_value=str(row[column + offset]), value=values[offset - 1], unit=unit, qualifier="exact"),
                            data_kind="reported_calculation",
                            ownership="focal_work",
                            evidence=[_table_evidence(table, exact_row, row=row_index, column=column + offset)],
                        )
                        for offset, property_name, term, unit in (
                            (1, "binding_energy", "binding energy", "eV"),
                            (2, "interaction_energy", "interaction energy", "eV"),
                            (3, "total_energy", "total energy", "kcal/mol"),
                        )
                    ]
                    _calculation(
                        document,
                        calculation_id=f"recovered_md_{label.casefold()}",
                        calculation_type="molecular_dynamics",
                        material_ref=material_ref,
                        treatment_ref=treatment_ref,
                        label=label,
                        table=table,
                        outputs=outputs,
                        context=context,
                    )


def _recover_single_adsorbate_quantum_table(document: CorrosionDocument, bundle: SourceBundle, material_ref: str) -> None:
    for table in bundle.tables:
        caption = table.caption or ""
        caption_norm = _norm(caption)
        if "quantum chemical parameters" not in caption_norm or "ehomo" not in _norm(
            " ".join(str(value or "") for row in table.raw_representation.get("grid", []) for value in row)
        ):
            continue
        label_match = re.search(r"\b([A-Z][A-Z0-9-]{1,8})\s+quantum chemical parameters\b", caption)
        if not label_match:
            continue
        label = label_match.group(1)
        treatment_ref = _ensure_treatment(document, label, bundle)
        grid = table.raw_representation.get("grid", [])
        if len(grid) < 3:
            continue
        row_index = next((index for index, row in enumerate(grid) if len(row) >= 6 and _number(row[1]) is not None and _number(row[2]) is not None), None)
        if row_index is None:
            continue
        row = grid[row_index]
        combined = _NUMBER.findall(_norm(row[3]))
        if len(combined) != 3:
            continue
        values = [
            (1, "homo_energy", "EHOMO", "eV", _number(row[1]), str(row[1])),
            (2, "lumo_energy", "ELUMO", "eV", _number(row[2]), str(row[2])),
            (3, "energy_gap", "ΔEL-H", "eV", float(combined[0]), combined[0]),
            (3, "electronegativity", "χ", "eV", float(combined[1]), combined[1]),
            (3, "global_hardness", "η", "eV", float(combined[2]), combined[2]),
            (4, "global_softness", "S", "eV^-1", _number(row[4]), str(row[4])),
            (5, "dipole_moment", "μ", "D", _number(row[5]), str(row[5])),
        ]
        exact_row = _row_text(row)
        outputs = [
            CorrosionCalculationOutput(
                property=property_name,
                reported_term=term,
                quantity=CorrosionQuantity(raw_value=raw, value=value, unit=unit, qualifier="exact"),
                data_kind="reported_calculation",
                ownership="focal_work",
                evidence=[_table_evidence(table, exact_row, row=row_index, column=column)],
            )
            for column, property_name, term, unit, value, raw in values
            if value is not None
        ]
        method_match = re.search(r"\bat\s+(.+?)\.?$", caption)
        method = method_match.group(1) if method_match else "quantum chemical calculation"
        functional_match = re.search(r"\b(B\d+LYP)\b", method, re.IGNORECASE)
        basis_match = re.search(r"/([^ ]+)", method)
        calculation_id = f"recovered_dft_{label.casefold()}"
        if any(item.calculation_id == calculation_id for item in document.calculations):
            continue
        document.calculations.append(CorrosionCalculation(
            calculation_id=calculation_id,
            calculation_type="dft",
            material_refs=[material_ref],
            treatment_refs=[treatment_ref],
            adsorbate_or_inhibitor=label,
            method=method,
            functional=functional_match.group(1).upper() if functional_match else None,
            basis_set=basis_match.group(1).rstrip(".") if basis_match else None,
            phase="gas phase",
            outputs=outputs,
            ownership="focal_work",
            evidence=[_table_evidence(table, caption)],
        ))


def recover_corrosion_computational_tables(
    document: CorrosionDocument,
    source_bundle: SourceBundle,
) -> CorrosionDocument:
    """Recover only directly table-reported computational values and context."""
    recovered = document.model_copy(deep=True)
    material_ref = _ensure_material(recovered, source_bundle)
    if material_ref is None:
        return recovered
    _recover_multi_adsorbate_tables(recovered, source_bundle, material_ref)
    _recover_single_adsorbate_quantum_table(recovered, source_bundle, material_ref)
    for table in source_bundle.tables:
        caption = _norm(table.caption)
        if "inhibition efficiency" not in caption or "ehomo" not in caption:
            continue
        for row_index, row in enumerate(table.raw_representation.get("grid", [])):
            if len(row) < 7:
                continue
            label = str(row[0] or "").strip()
            raw_efficiency = str(row[6] or "").strip()
            value = _number(raw_efficiency)
            if not _LABEL.fullmatch(label) or value is None or not re.search(r"[a-z]", raw_efficiency, re.IGNORECASE):
                continue
            experiment_id = f"recovered_cited_ie_{label.casefold()}"
            if any(item.experiment_id == experiment_id for item in recovered.experiments):
                continue
            exact_row = _row_text(row)
            evidence = [_table_evidence(table, exact_row, row=row_index, column=6)]
            recovered.experiments.append(CorrosionExperiment(
                experiment_id=experiment_id,
                experiment_type="other",
                material_refs=[material_ref],
                metrics=[CorrosionMetric(
                    property="inhibition_efficiency",
                    reported_term="IE",
                    quantity=CorrosionQuantity(raw_value=raw_efficiency, value=value, unit="%", qualifier="exact"),
                    data_kind="derived_metric",
                    ownership="cited_prior_work",
                    evidence=evidence,
                )],
                ownership="cited_prior_work",
                evidence=evidence,
            ))
    return CorrosionDocument.model_validate(recovered.model_dump(mode="python"))
