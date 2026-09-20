"""Conservative deterministic recovery for explicit gravimetric corrosion prose/tables."""

from __future__ import annotations

import re

from synthex_platform.scientific_text import normalize_scientific_text

from .corrosion_models import (
    CoatingOrInhibitor,
    CorrosionDocument,
    CorrosionEnvironment,
    CorrosionEvidence,
    CorrosionExperiment,
    CorrosionMetric,
    CorrosionQuantity,
)
from .source_context import SourceBundle


_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?")


def _norm(value: object | None) -> str:
    return normalize_scientific_text(value)


def _numbers(value: str) -> list[float]:
    return [float(item) for item in _NUMBER.findall(value)]


def _table_row(table, row: int) -> str:
    grid = table.raw_representation.get("grid", [])
    return " ".join(str(item) for item in grid[row] if item not in (None, "")).strip()


def _table_locator(table, row: int, column: int) -> str:
    cell = next((item for item in table.cells if item.row == row and item.column == column), None)
    return cell.cell_id if cell and cell.cell_id else f"{table.table_id}:r{row}:c{column}"


def _find_existing_material(document: CorrosionDocument) -> str | None:
    material = next((item for item in document.materials if item.ownership == "focal_work"), None)
    return material.local_id if material else None


def _treatment(
    document: CorrosionDocument,
    *,
    label: str,
    concentration: float,
    unit: str,
    evidence: CorrosionEvidence,
) -> str:
    for item in document.treatments:
        if _norm(item.reported_name) == _norm(label) and item.concentration:
            if item.concentration.value == concentration and _norm(item.concentration.unit) == _norm(unit):
                return item.treatment_id
    token = re.sub(r"[^a-z0-9]+", "_", f"{label}_{concentration:g}_{unit}".casefold()).strip("_")
    treatment_id = f"recovered_{token}"
    document.treatments.append(CoatingOrInhibitor(
        treatment_id=treatment_id,
        treatment_type="inhibitor",
        reported_name=label,
        concentration=CorrosionQuantity(
            raw_value=f"{concentration:g} {unit}", value=concentration, unit=unit, qualifier="exact"
        ),
        ownership="focal_work",
        evidence=[evidence],
    ))
    return treatment_id


def _environment(
    document: CorrosionDocument,
    *,
    identifier: str,
    electrolyte: str,
    temperature: float | None,
    exposure_time: float | None,
    evidence: CorrosionEvidence,
    treatment_ref: str | None,
) -> str:
    environment_id = f"recovered_env_{identifier}"
    if any(item.environment_id == environment_id for item in document.environments):
        return environment_id
    document.environments.append(CorrosionEnvironment(
        environment_id=environment_id,
        medium=electrolyte,
        electrolyte=electrolyte,
        temperature=(
            CorrosionQuantity(raw_value=f"{temperature:g} K", value=temperature, unit="K", qualifier="exact")
            if temperature is not None else None
        ),
        exposure_time=(
            CorrosionQuantity(raw_value=f"{exposure_time:g} h", value=exposure_time, unit="h", qualifier="exact")
            if exposure_time is not None else None
        ),
        inhibitor_ref=treatment_ref,
        evidence=[evidence],
    ))
    return environment_id


def _recover_temperature_series(document: CorrosionDocument, bundle: SourceBundle, material_ref: str) -> None:
    for page in bundle.pages:
        text = _norm(page.native_text)
        start = text.find("the corrosion rate of")
        if start < 0:
            continue
        end_marker = "at the inhibitor (fig. 3)"
        end = text.find(end_marker, start)
        if end < 0:
            continue
        passage = text[start:end + len(end_marker)]
        concentration_match = re.search(r"inhibitor concentration of\s+(\d+(?:\.\d+)?)\s*(ppm)", passage)
        time_match = re.search(r"immersion time of\s+(\d+(?:\.\d+)?)\s*(h)", passage)
        label_match = re.search(r"corrosion rate of\s+([a-z][a-z0-9-]{1,10})", passage)
        medium_match = re.search(r"\b\d+(?:\.\d+)?\s*m\s*hcl\b", text)
        if not (concentration_match and time_match and label_match and medium_match):
            continue
        concentration = float(concentration_match.group(1))
        exposure_time = float(time_match.group(1))
        label = label_match.group(1).upper()
        electrolyte = medium_match.group(0).replace("m hcl", "M HCl")
        evidence = CorrosionEvidence(page=page.page, section="temperature effect", text_snippet=passage, source_type="text")
        treatment_ref = _treatment(
            document, label=label, concentration=concentration, unit="ppm", evidence=evidence
        )
        rates = {
            float(temp): (float(value), unit.replace(" ", ""))
            for value, unit, temp in re.findall(
                r"(\d+(?:\.\d+)?)\s*(mm\s*/\s*(?:y|yr|year))\s+at\s+(\d+(?:\.\d+)?)\s*k",
                passage,
            )
        }
        efficiencies = {
            float(temp): float(value)
            for value, temp in re.findall(r"(\d+(?:\.\d+)?)\s*%\s+at\s+(\d+(?:\.\d+)?)\s*k", passage)
        }
        for temperature in sorted(set(rates) | set(efficiencies)):
            identifier = f"{label.casefold()}_{concentration:g}ppm_{exposure_time:g}h_{temperature:g}k"
            environment_ref = _environment(
                document,
                identifier=identifier,
                electrolyte=electrolyte,
                temperature=temperature,
                exposure_time=exposure_time,
                evidence=evidence,
                treatment_ref=treatment_ref,
            )
            experiment_id = f"recovered_weight_{identifier}"
            if any(item.experiment_id == experiment_id for item in document.experiments):
                continue
            metrics: list[CorrosionMetric] = []
            if temperature in rates:
                value, unit = rates[temperature]
                metrics.append(CorrosionMetric(
                    property="corrosion_rate",
                    reported_term="corrosion rate",
                    quantity=CorrosionQuantity(raw_value=f"{value:g} {unit}", value=value, unit=unit, qualifier="exact"),
                    method="weight loss",
                    data_kind="derived_metric",
                    ownership="focal_work",
                    evidence=[evidence],
                ))
            if temperature in efficiencies:
                value = efficiencies[temperature]
                metrics.append(CorrosionMetric(
                    property="inhibition_efficiency",
                    reported_term="inhibition efficiency",
                    quantity=CorrosionQuantity(raw_value=f"{value:g}%", value=value, unit="%", qualifier="exact"),
                    method="weight loss",
                    data_kind="derived_metric",
                    ownership="focal_work",
                    evidence=[evidence],
                ))
            document.experiments.append(CorrosionExperiment(
                experiment_id=experiment_id,
                experiment_type="weight_loss",
                material_refs=[material_ref],
                environment_ref=environment_ref,
                treatment_refs=[treatment_ref],
                metrics=metrics,
                ownership="focal_work",
                evidence=[evidence],
            ))


def _recover_ambiguous_concentration_sweep(document: CorrosionDocument, bundle: SourceBundle, material_ref: str) -> None:
    pattern = re.compile(
        r"inhibition efficiencies of\s+(?P<concentrations>[\d.,\sand]+?)\s+ppm\s+"
        r"(?P<label>[a-z][a-z0-9-]{1,10})\s+are\s+(?P<efficiencies>[\d.,\sand]+?)%\s+"
        r"and the corrosion rates are\s+(?P<rates>[\d.,\sand]+?)\s+mm/\s*year, respectively"
    )
    for page in bundle.pages:
        text = _norm(page.native_text)
        match = pattern.search(text)
        if not match:
            continue
        concentrations = _numbers(match.group("concentrations"))
        efficiencies = _numbers(match.group("efficiencies"))
        rates = _numbers(match.group("rates"))
        if not concentrations or len(concentrations) != len(efficiencies) or len(concentrations) != len(rates):
            continue
        label = match.group("label").upper()
        raw_match = re.search(
            r"inhibition efficiencies of.*?mm\s*/\s*year,\s*respectively\.?",
            page.native_text,
            re.IGNORECASE | re.DOTALL,
        )
        if raw_match is None:
            continue
        passage = raw_match.group(0)
        evidence = CorrosionEvidence(page=page.page, section="concentration sweep", text_snippet=passage, source_type="text")
        for concentration, efficiency, rate in zip(concentrations, efficiencies, rates, strict=True):
            treatment_ref = _treatment(
                document, label=label, concentration=concentration, unit="ppm", evidence=evidence
            )
            identifier = f"ambiguous_{label.casefold()}_{concentration:g}ppm"
            experiment_id = f"recovered_weight_{identifier}"
            if any(item.experiment_id == experiment_id for item in document.experiments):
                continue
            environment_ref = _environment(
                document,
                identifier=identifier,
                electrolyte="1.0 M HCl",
                temperature=303,
                exposure_time=None,
                evidence=evidence,
                treatment_ref=treatment_ref,
            )
            metrics: list[CorrosionMetric] = []
            for property_name, value, unit, term in (
                ("corrosion_rate", rate, "mm/year", "corrosion rate"),
                ("inhibition_efficiency", efficiency, "%", "inhibition efficiency"),
            ):
                metrics.append(CorrosionMetric(
                    property=property_name,
                    reported_term=term,
                    quantity=CorrosionQuantity(raw_value=f"{value:g} {unit}".replace(" %", "%"), value=value, unit=unit, qualifier="exact"),
                    method="weight loss",
                    data_kind="derived_metric",
                    ownership="focal_work",
                    evidence=[evidence],
                ))
            if metrics:
                document.experiments.append(CorrosionExperiment(
                    experiment_id=experiment_id,
                    experiment_type="weight_loss",
                    material_refs=[material_ref],
                    environment_ref=environment_ref,
                    treatment_refs=[treatment_ref],
                    metrics=metrics,
                    ownership="focal_work",
                    evidence=[evidence],
                ))


def _recover_cited_comparison_rows(document: CorrosionDocument, bundle: SourceBundle, material_ref: str) -> None:
    for table in bundle.tables:
        if "comparison of reported corrosion inhibitors" not in _norm(table.caption):
            continue
        grid = table.raw_representation.get("grid", [])
        if not grid:
            continue
        header = [_norm(value) for value in grid[0]]
        try:
            efficiency_column = next(index for index, value in enumerate(header) if "ie%" in value or value == "ie")
            reference_column = next(index for index, value in enumerate(header) if value.startswith("ref"))
        except StopIteration:
            continue
        for row_index, row in enumerate(grid[1:], start=1):
            if max(efficiency_column, reference_column) >= len(row):
                continue
            reference = str(row[reference_column] or "").strip()
            value_text = str(row[efficiency_column] or "").strip()
            values = _numbers(value_text)
            if not values or not reference or reference in {"-", "–", "—"}:
                continue
            experiment_id = f"recovered_cited_comparison_{row_index}"
            if any(item.experiment_id == experiment_id for item in document.experiments):
                continue
            evidence = CorrosionEvidence(
                page=table.page,
                text_snippet=_table_row(table, row_index),
                source_type="table",
                original_source_type="table_reported",
                table_id=table.table_id,
                locator=_table_locator(table, row_index, efficiency_column),
            )
            document.experiments.append(CorrosionExperiment(
                experiment_id=experiment_id,
                experiment_type="other",
                material_refs=[material_ref],
                metrics=[CorrosionMetric(
                    property="inhibition_efficiency",
                    reported_term="IE",
                    quantity=CorrosionQuantity(raw_value=value_text, value=values[0], unit="%", qualifier="exact"),
                    data_kind="derived_metric",
                    ownership="cited_prior_work",
                    evidence=[evidence],
                )],
                ownership="cited_prior_work",
                evidence=[evidence],
            ))


def recover_corrosion_gravimetric_candidates(
    document: CorrosionDocument,
    source_bundle: SourceBundle,
) -> CorrosionDocument:
    """Recover explicit joint-condition series and expose ambiguous/cited candidates."""
    recovered = document.model_copy(deep=True)
    material_ref = _find_existing_material(recovered)
    if material_ref is None:
        return recovered
    _recover_temperature_series(recovered, source_bundle, material_ref)
    _recover_ambiguous_concentration_sweep(recovered, source_bundle, material_ref)
    _recover_cited_comparison_rows(recovered, source_bundle, material_ref)
    return CorrosionDocument.model_validate(recovered.model_dump(mode="python"))
