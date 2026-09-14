from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from synthex_platform.extraction import BatteryGeminiExtractor, assemble_battery_archive

REPO_ROOT = Path(__file__).resolve().parent
GOLD_PATH = REPO_ROOT / "benchmark" / "batteries_v1" / "batteries_11_00142_gold.json"
OUTPUT_DIR = REPO_ROOT / "benchmark" / "outputs"


def console_report_json(report):
    """Render console output safely even when Windows uses a legacy code page."""
    return json.dumps(report, indent=2, ensure_ascii=True)


def _close(a, b, rel=1e-4, abs_tol=1e-9):
    return a is not None and math.isclose(float(a), float(b), rel_tol=rel, abs_tol=abs_tol)


def _norm_text(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _norm_unit(value):
    if isinstance(value, str) and any(symbol in value for symbol in ("Ω", "Ω")):
        return "ohm"
    normalized = _norm_text(value)
    aliases = {
        "mahg": "mah/g",
        "mahg1": "mah/g",
        "ohm": "ohm",
        "omega": "ohm",
        "cm2s": "cm2/s",
        "cm2s1": "cm2/s",
        "percent": "%",
    }
    if value == "%":
        return "%"
    return aliases.get(normalized, normalized)


def _matches_percent(quantity, expected_percent):
    if quantity is None or quantity.value is None:
        return False
    value = quantity.value
    if _norm_text(quantity.unit) in {"fraction", "massfraction"}:
        value *= 100
    return _close(value, expected_percent)


def _point_evidence(point):
    evidence = point.evidence
    if evidence is None:
        return []
    return evidence if isinstance(evidence, list) else [evidence]


def _has_value_evidence(point, expected_value):
    value_token = str(expected_value).lower().split("e", 1)[0]
    return any(
        ev.page is not None
        and ev.verbatim_match is True
        and bool((ev.text_snippet or "").strip())
        and value_token in (ev.text_snippet or "").lower()
        for ev in _point_evidence(point)
    )


def _material_and_variant_match(doc, group, expected):
    expected_variant = expected.get("variant")
    variant_match = re.search(r"\d+(?:\.\d+)?", str(expected_variant or ""))
    variant_values = [group.variant_label]
    if group.calcination_temperature:
        variant_values.extend([group.calcination_temperature.raw_value, group.calcination_temperature.value])
    variant_ok = not expected_variant or bool(
        variant_match and variant_match.group(0) in " ".join(str(x) for x in variant_values if x is not None)
    )

    expected_formula = _norm_text("Li2FeTiO4")
    material = next((m for m in doc.materials if m.material_id == group.material_ref), None)
    reported_formula = (material.formula if material else None) or group.cathode or group.material_ref
    material_ok = _norm_text(reported_formula) == expected_formula
    return material_ok and variant_ok


def _conflict_is_preserved(group, expected):
    conflict = expected.get("c_rate_conflict") or {}
    if not conflict:
        return True
    expected_values = {_norm_text(value) for value in conflict.get("reported_values", [])}
    for item in group.condition_conflicts:
        if _norm_text(item.field) != "crate" or item.status != "conflicted" or item.resolved_value is not None:
            continue
        reported = {_norm_text(value.value) for value in item.reported_values}
        evidence_present = all(bool(value.evidence) for value in item.reported_values)
        if expected_values <= reported and evidence_present:
            return True
    return False


def evaluate(doc):
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    structural_checks = []

    def add(name, ok, observed=None, expected=None):
        structural_checks.append({"check": name, "pass": bool(ok), "observed": observed, "expected": expected})

    add("title", doc.source.title == gold["paper"]["title"], doc.source.title, gold["paper"]["title"])
    add("DOI", (doc.source.doi or "").lower() == gold["paper"]["doi"], doc.source.doi, gold["paper"]["doi"])
    add("materials_synthesis type", "materials_synthesis" in doc.paper_types, doc.paper_types, True)
    add("electrode_fabrication type", "electrode_fabrication" in doc.paper_types, doc.paper_types, True)
    add("cell_assembly type", "cell_assembly" in doc.paper_types, doc.paper_types, True)
    add("electrochemical_performance type", "electrochemical_performance" in doc.paper_types, doc.paper_types, True)
    add("impedance_eis type", "impedance_eis" in doc.paper_types, doc.paper_types, True)

    mat = next((m for m in doc.materials if (m.formula or "").replace(" ", "") == "Li2FeTiO4"), None)
    add("Li2FeTiO4 material", mat is not None, mat.formula if mat else None, "Li2FeTiO4")
    add("sol-gel synthesis", bool(mat and mat.synthesis and "sol" in (mat.synthesis.method or "").lower()), mat.synthesis.method if mat and mat.synthesis else None, "sol-gel")

    groups = doc.battery_groups
    all_points = [(group, point) for group in groups for point in group.performance_points]

    # Search resolved shared/inline protocol data.
    protocols = list(doc.shared_protocols)
    protocols += [type("P", (), {"electrode_fabrication":g.electrode_fabrication,"cell_assembly":g.cell_assembly,"electrochemical_testing":g.electrochemical_testing}) for g in groups]
    ef = next((p.electrode_fabrication for p in protocols if getattr(p, "electrode_fabrication", None)), None)
    ca = next((p.cell_assembly for p in protocols if getattr(p, "cell_assembly", None)), None)
    et = next((p.electrochemical_testing for p in protocols if getattr(p, "electrochemical_testing", None)), None)
    add("electrode fabrication extracted", ef is not None, bool(ef), True)
    add("80 wt% active material", bool(ef and _matches_percent(ef.active_material_fraction, 80)), ef.active_material_fraction.model_dump() if ef and ef.active_material_fraction else None, 80)
    add("CR2032 cell assembly", bool(ca and ca.cell_format and "2032" in ca.cell_format), ca.cell_format if ca else None, "CR2032")
    add("100 uL electrolyte", bool(ca and ca.electrolyte_volume and _close(ca.electrolyte_volume.value, 100)), ca.electrolyte_volume.model_dump() if ca and ca.electrolyte_volume else None, 100)
    add("CV 0.1 mV/s", bool(et and et.cv_scan_rate and _close(et.cv_scan_rate.value, 0.1)), et.cv_scan_rate.model_dump() if et and et.cv_scan_rate else None, 0.1)
    add("100-cycle long-term test", bool(et and et.long_term_cycles == 100), et.long_term_cycles if et else None, 100)

    performance_checks = []
    for expected in gold["performance_assertions"]:
        candidates = [
            (group, point)
            for group, point in all_points
            if point.property == expected["property"] and _close(point.value, expected["value"])
        ]
        best = None
        best_rank = -1
        for group, point in candidates:
            value_pass = _norm_unit(point.unit) == _norm_unit(expected.get("unit"))
            sample_ok = _material_and_variant_match(doc, group, expected)
            cycle_ok = expected.get("cycle") is None or point.cycle == expected["cycle"]
            method_ok = all(
                _norm_text(term) in _norm_text(point.method)
                for term in expected.get("method_contains", [])
            )

            c_rate_status = expected.get("c_rate_status", "not_required")
            if c_rate_status == "conflicted":
                c_rate_ok = point.c_rate is None and _conflict_is_preserved(group, expected)
            elif expected.get("c_rate") is not None:
                c_rate_ok = _norm_text(point.c_rate) == _norm_text(expected["c_rate"])
            else:
                c_rate_ok = True

            conditions_pass = sample_ok and cycle_ok and method_ok and c_rate_ok
            provenance_pass = _has_value_evidence(point, expected["value"])
            rank = sum((value_pass, conditions_pass, provenance_pass))
            if rank > best_rank:
                best_rank = rank
                best = {
                    "property": expected["property"],
                    "expected": expected,
                    "observed": {
                        "group_id": group.group_id,
                        "variant": group.variant_label,
                        "material_ref": group.material_ref,
                        "value": point.value,
                        "unit": point.unit,
                        "cycle": point.cycle,
                        "c_rate": point.c_rate,
                        "method": point.method,
                        "evidence_count": len(_point_evidence(point)),
                    },
                    "value_pass": value_pass,
                    "conditions_pass": conditions_pass,
                    "provenance_pass": provenance_pass,
                    "sample_variant_pass": sample_ok,
                    "cycle_pass": cycle_ok,
                    "method_pass": method_ok,
                    "c_rate_pass": c_rate_ok,
                    "c_rate_status": c_rate_status,
                }
        if best is None:
            best = {
                "property": expected["property"],
                "expected": expected,
                "observed": None,
                "value_pass": False,
                "conditions_pass": False,
                "provenance_pass": False,
                "sample_variant_pass": False,
                "cycle_pass": False,
                "method_pass": False,
                "c_rate_pass": False,
                "c_rate_status": expected.get("c_rate_status", "not_required"),
            }
        best["pass"] = best["value_pass"] and best["conditions_pass"] and best["provenance_pass"]
        performance_checks.append(best)

    def accuracy(key, checks):
        return round(sum(bool(check[key]) for check in checks) / max(len(checks), 1), 3)

    structural_accuracy = accuracy("pass", structural_checks)
    value_accuracy = accuracy("value_pass", performance_checks)
    condition_accuracy = accuracy("conditions_pass", performance_checks)
    provenance_coverage = accuracy("provenance_pass", performance_checks)
    overall_score = round(
        (structural_accuracy + value_accuracy + condition_accuracy + provenance_coverage) / 4,
        3,
    )
    strict_summaries = [
        {
            "check": f"strict performance {check['property']}={check['expected']['value']}",
            "pass": check["pass"],
            "observed": check["observed"],
            "expected": check["expected"],
        }
        for check in performance_checks
    ]
    checks = structural_checks + strict_summaries
    return {
        "passed": sum(check["pass"] for check in checks),
        "total": len(checks),
        "score": overall_score,
        "structural_accuracy": structural_accuracy,
        "value_accuracy": value_accuracy,
        "condition_association_accuracy": condition_accuracy,
        "provenance_coverage": provenance_coverage,
        "overall_score": overall_score,
        "checks": checks,
        "performance_checks": performance_checks,
    }


def main():
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python benchmark_battery_material.py "path/to/batteries-11-00142.pdf"')
    extractor = BatteryGeminiExtractor(provider_mode="benchmark")
    doc = extractor.extract_pdf(sys.argv[1])
    archive = assemble_battery_archive(doc, model=extractor.model)
    report = evaluate(doc)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "batteries_11_00142_extracted_document.json").write_text(json.dumps(doc.model_dump(exclude_none=True), indent=2, ensure_ascii=False), encoding="utf-8")
    (OUTPUT_DIR / "batteries_11_00142_archive.json").write_text(json.dumps(archive.model_dump(exclude_none=True), indent=2, ensure_ascii=False), encoding="utf-8")
    (OUTPUT_DIR / "batteries_11_00142_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(console_report_json(report))
    print("\nSaved extracted document, archive and benchmark report under benchmark/outputs/.")

if __name__ == "__main__":
    main()
