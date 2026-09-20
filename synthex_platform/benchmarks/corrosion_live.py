"""Controlled live Corrosion V1 benchmark preparation, scoring, and diagnostics.

This module does not make provider calls at import time. A live run is deliberately one
paper at a time, uses benchmark provider mode, disables Serper/search enrichment, and
writes only to the git-ignored ``output/`` workspace.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from synthex_platform.benchmarks.corrosion import (
    CorrosionBenchmarkScore,
    CorrosionExpectedObservation,
    CorrosionExpectedQuarantine,
    score_corrosion_archive,
)
from synthex_platform.extraction import SynthexExtractionPipeline
from synthex_platform.extraction.corrosion_assembler import assemble_corrosion_archive
from synthex_platform.extraction.corrosion_computational_recovery import recover_corrosion_computational_tables
from synthex_platform.extraction.corrosion_evidence import verify_corrosion_evidence_item
from synthex_platform.extraction.corrosion_evidence import verify_corrosion_document_evidence
from synthex_platform.extraction.corrosion_gravimetric_recovery import recover_corrosion_gravimetric_candidates
from synthex_platform.extraction.corrosion_models import CorrosionDocument, CorrosionEvidence
from synthex_platform.extraction.corrosion_table_recovery import recover_corrosion_parameter_tables
from synthex_platform.extraction.source_context import build_source_bundle
from synthex_platform.visual.sidecar_store import VisualSidecarStore


HOLDOUT_CASE_ID = "CORR-HOLDOUT-I"

_EXPERIMENT_TYPE_ALIASES = {
    "electrochemical impedance spectroscopy": "eis",
    "electrochemical_impedance_spectroscopy": "eis",
    "impedance spectroscopy": "eis",
    "eis": "eis",
    "potentiodynamic polarization": "potentiodynamic_polarization",
    "potentiodynamic_polarization": "potentiodynamic_polarization",
    "linear polarization": "linear_polarization",
    "linear_polarization": "linear_polarization",
    "weight loss": "weight_loss",
    "weight_loss": "weight_loss",
}


@dataclass(frozen=True)
class CorrosionLiveCase:
    case_id: str
    role: str
    filename: str
    title: str
    doi: str
    pdf_path: Path
    gold_path: Path | None
    expected_domain: str


def _benchmark_root(repo_root: str | Path) -> Path:
    return Path(repo_root).resolve() / "benchmark" / "corrosion_v1"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_experiment_type(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return _EXPERIMENT_TYPE_ALIASES.get(text.casefold(), text)


def load_live_case(case_id: str, repo_root: str | Path) -> CorrosionLiveCase:
    """Resolve one locked benchmark case without invoking external services."""
    case_id = case_id.strip().upper()
    if case_id == HOLDOUT_CASE_ID:
        raise ValueError(
            "CORR-HOLDOUT-I is reserved as the localized-corrosion holdout and is not available for tuning/live Stage 3 runs."
        )

    root = _benchmark_root(repo_root)
    manifest = _read_json(root / "corpus_manifest.json")
    entry = next((item for item in manifest.get("entries", []) if item.get("id") == case_id), None)
    if entry is None:
        known = ", ".join(item.get("id", "") for item in manifest.get("entries", []) if item.get("id") != HOLDOUT_CASE_ID)
        raise ValueError(f"Unknown Corrosion V1 case {case_id!r}. Available cases: {known}")

    pdf_path = root / "corpus pdfs" / entry["filename"]
    if not pdf_path.exists():
        raise FileNotFoundError(f"Benchmark PDF is missing: {pdf_path}")

    gold_path = root / "gold" / f"{case_id}.json"
    if not gold_path.exists():
        gold_path = None

    expected_domain = "not_corrosion" if entry.get("role") == "non_corrosion_negative_control" else "corrosion"
    return CorrosionLiveCase(
        case_id=case_id,
        role=str(entry.get("role") or ""),
        filename=str(entry["filename"]),
        title=str(entry.get("expected_title") or ""),
        doi=str(entry.get("expected_doi") or ""),
        pdf_path=pdf_path,
        gold_path=gold_path,
        expected_domain=expected_domain,
    )


def expectations_from_gold(gold: dict[str, Any]) -> tuple[CorrosionExpectedObservation, ...]:
    """Translate explicitly scored numeric gold observations into scorer assertions.

    Experiment labels are mapped only into the Corrosion V1 canonical taxonomy. No
    scientific value, unit, normalization-basis, or reference-electrode conversion is
    performed. Explicit inhibitor associations in the gold conditions are retained so
    swapped inhibitor/value assignments cannot receive association credit.
    """
    expected: list[CorrosionExpectedObservation] = []
    benchmark_context = gold.get("benchmark_context") if isinstance(gold.get("benchmark_context"), dict) else {}
    for item in gold.get("scored_numeric_observations", []):
        conditions = item.get("conditions") if isinstance(item.get("conditions"), dict) else {}
        inhibitor = conditions.get("inhibitor")
        if isinstance(inhibitor, str) and inhibitor.strip().casefold() in {"none", "no inhibitor", "blank", "control"}:
            inhibitor = None
        expected.append(CorrosionExpectedObservation(
            metric=str(item["metric"]),
            value=float(item["value"]),
            unit=(str(item["unit"]) if item.get("unit") is not None else None),
            experiment_type=_canonical_experiment_type(item.get("experiment_type")),
            record_type=item.get("record_type"),
            calculation_type=item.get("calculation_type"),
            material_contains=item.get("material_contains"),
            treatment_contains=(
                item.get("treatment_contains")
                or inhibitor
                or conditions.get("coating")
                or benchmark_context.get("treatment_contains")
            ),
            reference_electrode=item.get("reference_electrode"),
            exposure_time=(conditions.get("exposure_time") or conditions.get("immersion_time")),
            temperature=conditions.get("temperature"),
            treatment_concentration=(
                conditions.get("inhibitor_concentration")
                or conditions.get("treatment_concentration")
                or conditions.get("concentration")
            ),
            electrolyte_contains=(
                conditions.get("electrolyte")
                or conditions.get("molten_salt")
                or conditions.get("environment")
                or conditions.get("medium")
            ),
            equivalent_circuit_contains=(
                item.get("equivalent_circuit_contains")
                or conditions.get("equivalent_circuit_contains")
                or conditions.get("equivalent_circuit")
            ),
            reported_term=item.get("reported_term"),
            data_kind=item.get("data_kind"),
            element_role=item.get("element_role"),
            unit_category=item.get("unit_category"),
            adsorbate_contains=item.get("adsorbate_contains"),
            surface_contains=item.get("surface_contains"),
            method_contains=item.get("method_contains"),
            software_contains=item.get("software_contains"),
            functional_contains=item.get("functional_contains"),
            basis_set_contains=item.get("basis_set_contains"),
            tolerance_abs=float(item.get("tolerance_abs", 1e-9)),
            required=bool(item.get("required", True)),
        ))
    return tuple(expected)


_CALCULATION_GOLD_PROPERTIES = {
    "EHOMO_eV": ("homo_energy", "eV", "EHOMO"),
    "ELUMO_eV": ("lumo_energy", "eV", "ELUMO"),
    "chemical_potential_eV": ("chemical_potential", "eV", "chemical potential"),
    "electron_transfer_number_e": ("electron_transfer_number", "e", "ΔN"),
    "global_hardness_eV": ("global_hardness", "eV", "global hardness"),
    "binding_energy_eV": ("binding_energy", "eV", "binding energy"),
    "interaction_energy_eV": ("interaction_energy", "eV", "interaction energy"),
    "minimum_total_energy_kcal_per_mol": ("total_energy", "kcal/mol", "total energy"),
}


def calculation_expectations_from_gold(gold: dict[str, Any]) -> tuple[CorrosionExpectedObservation, ...]:
    """Translate reviewed calculation tables without computing any missing descriptor."""
    setup = gold.get("computational_setup") if isinstance(gold.get("computational_setup"), dict) else {}
    expected: list[CorrosionExpectedObservation] = []
    for calculation in gold.get("calculation_gold", []):
        outputs = calculation.get("outputs") if isinstance(calculation.get("outputs"), dict) else {}
        for key, value in outputs.items():
            mapping = _CALCULATION_GOLD_PROPERTIES.get(key)
            if mapping is None:
                continue
            metric, unit, reported_term = mapping
            calculation_type = "molecular_dynamics" if metric in {
                "binding_energy", "interaction_energy", "total_energy"
            } else "dft"
            expected.append(CorrosionExpectedObservation(
                metric=metric,
                value=float(value),
                unit=unit,
                record_type="calculation",
                calculation_type=calculation_type,
                material_contains=calculation.get("surface") or setup.get("surface"),
                adsorbate_contains=calculation.get("adsorbate"),
                surface_contains=calculation.get("surface"),
                reported_term=reported_term,
                data_kind="reported_calculation",
                software_contains="DMol3" if calculation_type == "dft" else "Materials Studio",
                functional_contains=setup.get("exchange_correlation_functional") if calculation_type == "dft" else None,
                basis_set_contains=setup.get("basis_set") if calculation_type == "dft" else None,
            ))
    return tuple(expected)


def all_expectations_from_gold(gold: dict[str, Any]) -> tuple[CorrosionExpectedObservation, ...]:
    """Return experimental and computational assertions without cross-casting either."""
    return (*expectations_from_gold(gold), *calculation_expectations_from_gold(gold))


def quarantine_expectations_from_gold(gold: dict[str, Any]) -> tuple[CorrosionExpectedQuarantine, ...]:
    """Translate explicit must-quarantine gold assertions without inferring omissions."""
    return tuple(
        CorrosionExpectedQuarantine(
            metric=str(item["metric"]),
            value=float(item["value"]),
            unit=(str(item["unit"]) if item.get("unit") is not None else None),
            reason=str(item["reason"]),
            tolerance_abs=float(item.get("tolerance_abs", 1e-9)),
        )
        for item in gold.get("quarantine_assertions", [])
    )


def build_live_pipeline(output_directory: str | Path) -> SynthexExtractionPipeline:
    """Build the quota-conscious live benchmark pipeline without network search or OCR."""
    return SynthexExtractionPipeline(
        search_assisted=False,
        find_supplementary=False,
        enable_ocr=False,
        provider_mode="benchmark",
        visual_sidecar_store=VisualSidecarStore(output_directory),
    )


def _score_payload(score: CorrosionBenchmarkScore | None) -> dict[str, Any] | None:
    return score.as_dict() if score is not None else None


def _find_quarantine_lists(value: Any) -> list[list[dict[str, Any]]]:
    found: list[list[dict[str, Any]]] = []
    if isinstance(value, dict):
        quarantine = value.get("quarantine")
        if isinstance(quarantine, list) and all(isinstance(item, dict) for item in quarantine):
            found.append(quarantine)
        for child in value.values():
            found.extend(_find_quarantine_lists(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_find_quarantine_lists(child))
    return found


def _metric_summary(metric: dict[str, Any], *, reason: str | None = None, path: str | None = None) -> dict[str, Any]:
    quantity = metric.get("quantity") if isinstance(metric.get("quantity"), dict) else {}
    evidence = metric.get("evidence") if isinstance(metric.get("evidence"), list) else []
    return {
        "property": metric.get("property"),
        "reported_term": metric.get("reported_term"),
        "raw_value": quantity.get("raw_value", metric.get("raw_value")),
        "value": quantity.get("value", metric.get("value")),
        "unit": quantity.get("unit", metric.get("unit")),
        "ownership": metric.get("ownership"),
        "evidence_count": len(evidence),
        "verified_evidence_count": sum(
            1 for item in evidence
            if isinstance(item, dict) and item.get("verbatim_match") is True
        ),
        "reason": reason,
        "path": path,
    }


def _evidence_dicts(value: Any):
    if isinstance(value, dict):
        if "text_snippet" in value and set(value).issubset(set(CorrosionEvidence.model_fields)):
            yield value
            return
        for child in value.values():
            yield from _evidence_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _evidence_dicts(child)


def reverify_live_quarantine_evidence(case_id: str, repo_root: str | Path) -> dict[str, Any]:
    """Re-check stored quarantined evidence against the locked PDF with current offline rules.

    This performs PDF/table parsing only. It does not call Gemini, Serper, OCR, or mutate
    the stored archive/report.
    """
    repo_root = Path(repo_root).resolve()
    case = load_live_case(case_id, repo_root)
    output_dir = repo_root / "output" / "corrosion_v1" / "live" / case.case_id
    archive_path = output_dir / "archive.json"
    if not archive_path.exists():
        raise FileNotFoundError(f"Live archive not found: {archive_path}")

    archive = _read_json(archive_path)
    bundle = build_source_bundle(
        case.pdf_path,
        source_filename=case.filename,
        enable_ocr=False,
        include_figures=False,
        sidecar_store=VisualSidecarStore(output_dir),
    )

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in archive.get("domain_payloads", []):
        for quarantine in _find_quarantine_lists(payload):
            for entry in quarantine:
                obj = entry.get("object")
                if not isinstance(obj, dict):
                    continue
                for raw in _evidence_dicts(obj):
                    token = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
                    if token in seen:
                        continue
                    seen.add(token)
                    evidence = CorrosionEvidence.model_validate(raw)
                    verified = verify_corrosion_evidence_item(evidence, bundle)
                    entries.append({
                        "snippet": evidence.text_snippet,
                        "page": evidence.page,
                        "table_id": evidence.table_id,
                        "source_type": evidence.source_type,
                        "original_source_type": evidence.original_source_type,
                        "was_verified": evidence.verbatim_match is True,
                        "verifies_now": verified.verbatim_match is True,
                        "verified_page": verified.page,
                        "verified_origin": verified.original_source_type,
                    })

    return {
        "case_id": case.case_id,
        "evidence_count": len(entries),
        "verified_before": sum(item["was_verified"] for item in entries),
        "verifies_now": sum(item["verifies_now"] for item in entries),
        "items": entries,
        "tables_detected": len(bundle.tables),
        "pages": len(bundle.pages),
    }


def diagnose_live_output(case_id: str, repo_root: str | Path) -> dict[str, Any]:
    """Inspect an existing live-run archive/report without making any provider calls."""
    repo_root = Path(repo_root).resolve()
    case_id = case_id.strip().upper()
    output_dir = repo_root / "output" / "corrosion_v1" / "live" / case_id
    archive_path = output_dir / "archive.json"
    report_path = output_dir / "report.json"
    if not archive_path.exists():
        raise FileNotFoundError(f"Live archive not found: {archive_path}")
    if not report_path.exists():
        raise FileNotFoundError(f"Live report not found: {report_path}")

    archive = _read_json(archive_path)
    report = _read_json(report_path)

    canonical_metrics: list[dict[str, Any]] = []
    experiment_summaries: list[dict[str, Any]] = []
    for experiment in archive.get("experiments", []):
        outputs = experiment.get("outputs") or []
        experiment_summaries.append({
            "experiment_id": experiment.get("experiment_id"),
            "experiment_type": experiment.get("experiment_type"),
            "material_ids": experiment.get("material_ids") or [],
            "output_count": len(outputs),
        })
        for metric in outputs:
            summary = _metric_summary(metric)
            summary["experiment_type"] = experiment.get("experiment_type")
            summary["experiment_id"] = experiment.get("experiment_id")
            canonical_metrics.append(summary)

    quarantine_entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in archive.get("domain_payloads", []):
        for quarantine in _find_quarantine_lists(payload):
            for entry in quarantine:
                token = json.dumps(entry, sort_keys=True, ensure_ascii=False, default=str)
                if token not in seen:
                    seen.add(token)
                    quarantine_entries.append(entry)

    quarantined_metrics: list[dict[str, Any]] = []
    for entry in quarantine_entries:
        obj = entry.get("object")
        reason = entry.get("reason")
        path = entry.get("path")
        if not isinstance(obj, dict):
            continue
        if "property" in obj and "quantity" in obj:
            quarantined_metrics.append(_metric_summary(obj, reason=reason, path=path))
        metrics = obj.get("metrics")
        if isinstance(metrics, list):
            for metric in metrics:
                if isinstance(metric, dict):
                    quarantined_metrics.append(_metric_summary(metric, reason=reason, path=path))

    reason_counts = Counter(
        str(entry.get("reason") or "unknown") for entry in quarantine_entries
    )

    return {
        "case_id": case_id,
        "archive_path": str(archive_path.relative_to(repo_root)),
        "report_path": str(report_path.relative_to(repo_root)),
        "archive_domain": (archive.get("metadata") or {}).get("domain"),
        "source_count": len(archive.get("sources", [])),
        "material_count": len(archive.get("materials", [])),
        "experiment_count": len(archive.get("experiments", [])),
        "canonical_metric_count": len(canonical_metrics),
        "canonical_metrics": canonical_metrics,
        "experiments": experiment_summaries,
        "quarantine_entry_count": len(quarantine_entries),
        "quarantine_reason_counts": dict(sorted(reason_counts.items())),
        "quarantined_metrics": quarantined_metrics,
        "score": report.get("score"),
        "extraction_diagnostics": report.get("extraction_diagnostics") or {},
        "provider_audit": report.get("provider_audit") or {},
    }


def replay_saved_live_corrosion_case(case_id: str, repo_root: str | Path) -> dict[str, Any]:
    """Replay a stored provider document through current deterministic recovery offline.

    The historical archive, report, and verified-document files are read-only inputs.
    No provider, search, or OCR service is invoked and no replay artifact is written.
    The historical score is reported separately from the post-recovery score so the
    deterministic layer is never presented as provider accuracy.
    """
    repo_root = Path(repo_root).resolve()
    case = load_live_case(case_id, repo_root)
    if case.gold_path is None:
        raise FileNotFoundError(f"Gold file not found for {case.case_id}")
    output_dir = repo_root / "output" / "corrosion_v1" / "live" / case.case_id
    document_path = output_dir / "verified_document.json"
    report_path = output_dir / "report.json"
    if not document_path.exists():
        raise FileNotFoundError(f"Saved provider document not found: {document_path}")
    if not report_path.exists():
        raise FileNotFoundError(f"Historical live report not found: {report_path}")

    historical_report = _read_json(report_path)
    document = CorrosionDocument.model_validate_json(document_path.read_text(encoding="utf-8"))
    bundle = build_source_bundle(
        case.pdf_path,
        source_filename=case.filename,
        enable_ocr=False,
        include_figures=False,
    )
    recovered = recover_corrosion_parameter_tables(document, bundle)
    recovered = recover_corrosion_gravimetric_candidates(recovered, bundle)
    recovered = recover_corrosion_computational_tables(recovered, bundle)
    verified = verify_corrosion_document_evidence(recovered, bundle)
    archive = assemble_corrosion_archive(verified, source_bundle=bundle)

    gold = _read_json(case.gold_path)
    expectations = all_expectations_from_gold(gold)
    quarantine_expectations = quarantine_expectations_from_gold(gold)
    score = score_corrosion_archive(archive, expectations, quarantine_expectations)
    return {
        "case_id": case.case_id,
        "provider_calls": 0,
        "historical_artifacts_mutated": False,
        "raw_provider_score": historical_report.get("score"),
        "post_recovery_score": score.as_dict(),
        "verified_document": verified,
        "archive": archive,
        "source_bundle": bundle,
    }


def run_live_corrosion_case(case_id: str, repo_root: str | Path) -> dict[str, Any]:
    """Run exactly one live benchmark paper and persist its archive/report under ``output/``."""
    repo_root = Path(repo_root).resolve()
    load_dotenv(repo_root / ".env", override=True)
    case = load_live_case(case_id, repo_root)

    output_dir = repo_root / "output" / "corrosion_v1" / "live" / case.case_id
    output_dir.mkdir(parents=True, exist_ok=True)
    pipeline = build_live_pipeline(output_dir)

    bundle = pipeline.build_source_bundle(case.pdf_path, source_filename=case.filename)
    route, archive = pipeline.extract_source_bundle(bundle, domain="auto")

    verified_document_path: Path | None = None
    if route.domain == "corrosion" and pipeline.last_corrosion_document is not None:
        verified_document_path = output_dir / "verified_document.json"
        verified_document_path.write_text(
            pipeline.last_corrosion_document.model_dump_json(indent=2, exclude_none=True),
            encoding="utf-8",
        )

    archive_path = output_dir / "archive.json"
    archive_path.write_text(archive.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")

    route_ok = route.domain != "corrosion" if case.expected_domain == "not_corrosion" else route.domain == case.expected_domain
    expectations: tuple[CorrosionExpectedObservation, ...] = ()
    quarantine_expectations: tuple[CorrosionExpectedQuarantine, ...] = ()
    score: CorrosionBenchmarkScore | None = None
    if case.gold_path is not None:
        gold = _read_json(case.gold_path)
        expectations = all_expectations_from_gold(gold)
        quarantine_expectations = quarantine_expectations_from_gold(gold)
        if route.domain == "corrosion" and expectations:
            score = score_corrosion_archive(archive, expectations, quarantine_expectations)

    report: dict[str, Any] = {
        "case_id": case.case_id,
        "role": case.role,
        "paper": {
            "filename": case.filename,
            "title": case.title,
            "doi": case.doi,
        },
        "run_policy": {
            "provider_mode": "benchmark",
            "search_assisted": False,
            "ocr_enabled": False,
            "one_paper_per_run": True,
            "production_archive_mutated": False,
        },
        "routing": {
            "expected_domain": case.expected_domain,
            "resolved_domain": route.domain,
            "confidence": route.confidence,
            "method": route.method,
            "route_ok": route_ok,
        },
        "gold_assertions": len(expectations) + len(quarantine_expectations),
        "score": _score_payload(score),
        "extraction_diagnostics": pipeline.last_extraction_diagnostics,
        "provider_audit": pipeline.last_provider_audit,
        "verified_document_path": (
            str(verified_document_path.relative_to(repo_root))
            if verified_document_path is not None
            else None
        ),
        "archive_path": str(archive_path.relative_to(repo_root)),
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    report["report_path"] = str(report_path.relative_to(repo_root))
    return report
