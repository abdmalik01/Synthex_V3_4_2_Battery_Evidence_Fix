"""Build a metadata-only, offline snapshot of the ten-domain program.

This reads existing manifests, closure audits, provider reports and Git state.
It never invokes a provider or copies source, gold, or raw response bodies.
"""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from benchmark.provider_audit.build_history import build as build_provider_history


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BENCHMARK = ROOT / "benchmark"
LEGACY = "not_standardized_in_legacy_v1"
DOMAINS = (
    "batteries", "catalysis", "corrosion", "mechanical",
    "additive_manufacturing", "photovoltaics", "thermoelectrics",
    "membranes", "semiconductors", "biomaterials",
)
FREEZE_COMMITS = {
    "batteries": "a273faa", "catalysis": "f67c42e", "corrosion": "1f267e3",
    "mechanical": "cce678c", "additive_manufacturing": "b59f532",
    "photovoltaics": "d03b6d4", "thermoelectrics": "0f7b63f",
    "membranes": "ad6f13d", "semiconductors": "9312a79",
}


def read(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True)
    return result.stdout.decode("utf-8", errors="replace").strip()


def classification(path: str) -> str:
    p = path.replace("\\", "/").lower()
    name = p.rsplit("/", 1)[-1]
    if name.startswith(".pytest") or "/.pytest" in p or p.startswith("tmp/") or name.endswith((".pyc", ".pyo")) or p.startswith(".pams") or p.startswith(".pt") or p.startswith(".py") or p.startswith(".pz"):
        return "G_pytest_temp_artifacts"
    if p.startswith("benchmark/system_audit/"):
        return "H_documentation_config"
    if p.startswith("benchmark/biomaterials_v1/") or "biomaterial" in p or "bioact" in p:
        return "B_biomaterials_pending_freeze"
    if "openai" in p:
        return "D_dormant_openai_work"
    if p.startswith("benchmark/corrosion_v1/") or "corrosion" in p:
        return "E_corrosion_historical_work"
    if p.startswith("benchmark/provider_audit/") or p.startswith("synthex_platform/providers/") or "provider_artifact" in p or "provider_audit" in p:
        return "C_provider_infrastructure"
    if p.startswith("benchmark/"):
        return "A_frozen_domain_scientific_work"
    if p.startswith("synthex_platform/") or p.startswith("tests_v3/"):
        return "F_pipeline_application_work"
    if p.endswith((".md", ".toml", ".yaml", ".yml", ".txt")) or p.startswith(".env") or p in {"requirements.txt", ".gitignore"}:
        return "H_documentation_config"
    return "I_unknown_requires_human_review"


def worktree() -> dict:
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=ROOT, capture_output=True, check=True,
    )
    chunks = status.stdout.decode("utf-8", errors="replace").split("\0")
    entries = []
    i = 0
    while i < len(chunks) and chunks[i]:
        chunk = chunks[i]
        state, path = chunk[:2], chunk[3:]
        row = {"path": path, "git_xy": state, "classification": classification(path)}
        if "R" in state or "C" in state:
            i += 1
            row["old_path"] = chunks[i]
        entries.append(row)
        i += 1
    ignored_provider = []
    ignored_raw = []
    ignored_file_count = 0
    output = ROOT / "output"
    if output.is_dir():
        for p in output.glob("**/*"):
            if not p.is_file() or not ({"provider_runs", "live"} & set(p.parts)):
                continue
            ignored_file_count += 1
            if p.name == "report.json":
                ignored_provider.append(rel(p))
            if p.name in {"raw_response.txt", "provider_raw_response.json"}:
                ignored_raw.append(rel(p))
    ignored_provider.sort()
    ignored_raw.sort()
    return {
        "head": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
        "divergence": git("rev-list", "--left-right", "--count", "origin/main...HEAD"),
        "staged_paths": [e["path"] for e in entries if e["git_xy"][0] not in {" ", "?"}],
        "entries": entries, "classification_counts": dict(Counter(e["classification"] for e in entries)),
        "ignored_provider_report_paths": ignored_provider,
        "ignored_provider_raw_response_paths": ignored_raw,
        "ignored_provider_artifact_file_count": ignored_file_count,
        "git_status_diagnostic": "permission-denied warnings for pre-existing tracked pytest artifacts may occur" if status.stderr else None,
    }


def cases_of(obj: dict) -> list[dict]:
    value = obj.get("cases") or []
    if isinstance(value, dict):
        value = list(value.values())
    return [v for v in value if isinstance(v, dict)]


def case_id(case: dict) -> str | None:
    return case.get("case_id") or case.get("id")


def choose(*values):
    return next((v for v in values if v is not None), None)


def count_of(obj: dict, *names: str):
    return choose(*(obj.get(name) for name in names))


def hash_index() -> dict[str, list[str]]:
    """Index local locked inputs by bytes, without reading them into outputs."""
    result: dict[str, list[str]] = {}
    for p in BENCHMARK.rglob("*"):
        if not p.is_file() or any(x in p.parts for x in ("outputs", "output", "provider_runs", "system_audit")):
            continue
        if p.suffix.lower() not in {".pdf", ".xlsx", ".xls", ".csv", ".zip", ".json"}:
            continue
        if p.suffix.lower() == ".json" and not p.name.startswith(("gold", "source_lock")) and "_gold" not in p.name:
            continue
        digest = sha256(p.read_bytes()).hexdigest()
        result.setdefault(digest, []).append(rel(p))
    return result


def lock_hash_audit(folder: Path, index: dict[str, list[str]]) -> dict:
    paths = sorted({
        *folder.glob("source_lock*.json"), *folder.glob("*_source_lock.json"),
        *folder.glob("source_locks.json"), *folder.glob("corpus_lock.json"),
    })
    verified, unresolved = 0, []
    def walk(value, path: Path):
        nonlocal verified
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("sha256") and isinstance(item, str) and len(item) == 64:
                    if index.get(item):
                        verified += 1
                    else:
                        unresolved.append({"lock": rel(path), "field": key, "sha256": item})
                else:
                    walk(item, path)
        elif isinstance(value, list):
            for item in value:
                walk(item, path)
    for path in paths:
        walk(read(path), path)
    return {"lock_files": [rel(p) for p in paths], "verified_hash_references": verified, "unresolved_hash_references": unresolved}


def closure_values(freeze: dict, closure: dict) -> tuple[object, object, object, object]:
    fclosure = freeze.get("closure") or {}
    totals = closure.get("totals") or fclosure.get("totals") or {}
    canonical = choose(count_of(closure, "canonical_output_total"), count_of(freeze, "canonical_output_total"), totals.get("canonical_outputs"))
    experiments = choose(count_of(closure, "experiment_count"), count_of(freeze, "experiment_count"), totals.get("experiments"))
    calculations = choose(count_of(closure, "calculation_count"), count_of(freeze, "calculation_count"), totals.get("calculations"))
    case_rows = cases_of(freeze) or cases_of(closure)
    def sum_complete(*keys: str):
        values = [choose(count_of(row, *keys), count_of(row.get("canonical_counts") or row.get("counts") or {}, *keys)) for row in case_rows]
        return sum(values) if values and all(isinstance(v, int) for v in values) else None
    canonical = choose(canonical, sum_complete("outputs", "canonical_outputs", "pv_outputs"))
    experiments = choose(experiments, sum_complete("experiments", "canonical_experiments", "pv_experiments"))
    calculations = choose(calculations, sum_complete("calculations", "canonical_calculations", "pv_calculations"))
    inv = choose(closure.get("invariant_pass_count"), closure.get("passed_invariants"), freeze.get("passed_invariants"), freeze.get("scientific_invariants_passed"), (fclosure.get("scientific_invariants") or {}).get("passed"))
    return canonical, experiments, calculations, inv


def build_domain_and_registry(index: dict[str, list[str]]) -> tuple[list[dict], list[dict], dict]:
    domains, registry = [], []
    safety = {}
    for domain in DOMAINS:
        folder = BENCHMARK / f"{domain}_v1"
        freeze_path = folder / "freeze_manifest.json"
        closure_path = folder / "closure_audit.json"
        freeze, closure = read(freeze_path), read(closure_path)
        by_id = {}
        for src in (cases_of(freeze), cases_of(closure)):
            for case in src:
                cid = case_id(case)
                if cid:
                    by_id.setdefault(cid, {}).update(case)
        if domain == "biomaterials":
            for lock in closure.get("locks", []):
                cid = lock.get("case_id")
                if cid in by_id:
                    source_path = Path(lock.get("source", ""))
                    gold_path = Path(lock.get("gold", ""))
                    try:
                        source_ref = rel(source_path)
                    except ValueError:
                        source_ref = None
                    try:
                        gold_ref = rel(gold_path)
                    except ValueError:
                        gold_ref = None
                    by_id[cid].update({
                        "source": source_ref, "doi": lock.get("doi"),
                        "gold_path": gold_ref,
                        "source_sha256": lock.get("source_sha256"),
                        "gold_sha256": lock.get("gold_sha256"),
                    })
        canonical, experiments, calculations, inv = closure_values(freeze, closure)
        fclosure = freeze.get("closure") or {}
        contamination = choose(closure.get("contamination"), freeze.get("contamination"), fclosure.get("contamination"), freeze.get("expected_contamination"))
        if contamination is None and fclosure:
            contamination = {k: v for k, v in fclosure.items() if "contamination" in k or "violations" in k or "leakage" in k}
        safety[domain] = {
            "reported": contamination,
            "basis": rel(closure_path if closure else freeze_path) if freeze or closure else None,
            "basis_kind": "closure_observed" if closure else "freeze_manifest_claim_or_expected",
        }
        gate = choose(freeze.get("live_gate"), closure.get("live_gate"), freeze.get("live_gate_satisfied"))
        if domain == "biomaterials":
            gate = False
        if isinstance(gate, dict):
            gate_satisfied = gate.get("satisfied")
            qualifying = {k: gate.get(k) for k in ("provider_name", "model_id", "run_id", "qualifying_case") if gate.get(k) is not None}
        else:
            gate_satisfied, qualifying = gate, None
        verified, unresolved = [], []
        for cid, case in sorted(by_id.items()):
            hash_fields = {**(case.get("source_hashes") or {}), **case}
            hashes = {k: v for k, v in hash_fields.items() if k.endswith("sha256") and isinstance(v, str) and len(v) == 64}
            match = {k: index.get(v, []) for k, v in hashes.items()}
            direct = {}
            for label, path_key, hash_key in (
                ("source", "locked_source_path", "source_sha256"),
                ("source", "source", "source_sha256"),
                ("gold", "gold_path", "gold_sha256"),
            ):
                reference = case.get(path_key)
                expected = hashes.get(hash_key)
                if reference and expected:
                    p = ROOT / reference
                    direct[label] = {"path": reference, "verified": p.is_file() and sha256(p.read_bytes()).hexdigest() == expected}
                    if not direct[label]["verified"]:
                        unresolved.append((cid, f"direct_{label}"))
            if case.get("source_lock_path"):
                p = ROOT / case["source_lock_path"]
                direct["source_lock"] = {"path": case["source_lock_path"], "exists": p.is_file()}
                if not p.is_file():
                    unresolved.append((cid, "source_lock_path"))
            verified.extend((cid, k) for k, v in match.items() if v)
            unresolved.extend((cid, k) for k, v in match.items() if not v)
            counts = case.get("canonical_counts") or case.get("counts") or {}
            score = case.get("deterministic_score") or {}
            registry.append({
                "domain": domain, "case_id": cid, "manifest": rel(freeze_path if freeze else closure_path),
                "source": choose(case.get("locked_source_path"), case.get("source"), case.get("source_lock_path")),
                "doi": case.get("doi"), "source_hashes": {k: v for k, v in hashes.items() if k != "gold_sha256"},
                "gold_sha256": hashes.get("gold_sha256"), "hash_matches": match,
                "direct_reference_checks": direct,
                "benchmark_type": choose(case.get("role"), case.get("benchmark_type")),
                "expected_route": case.get("expected_route"),
                "deterministic_output_count": choose(count_of(case, "outputs", "canonical_outputs", "pv_outputs", "gold_outputs"), count_of(counts, "outputs", "canonical_outputs"), score.get("expected_outputs")),
                "recovered_output_count": choose(case.get("matched_outputs"), score.get("exact_outputs")),
                "experiments": choose(count_of(case, "experiments", "canonical_experiments", "pv_experiments"), counts.get("experiments")),
                "calculations": choose(count_of(case, "calculations", "canonical_calculations", "pv_calculations"), counts.get("calculations")),
                "quarantine_count": choose(case.get("quarantine_noncanonical_count"), counts.get("quarantine")),
                "review_noncanonical_count": choose(case.get("noncanonical_candidates"), counts.get("noncanonical_or_review")),
                "invariant_status": case.get("invariant_status"), "evidence_status": case.get("evidence_status"),
                "ownership_status": case.get("ownership_status"),
            })
        if domain == "biomaterials":
            for lock in closure.get("locks", []):
                if isinstance(lock, dict):
                    for key in ("source", "gold"):
                        p = Path(lock.get(key, ""))
                        expected = lock.get(f"{key}_sha256")
                        if not p.is_file() or sha256(p.read_bytes()).hexdigest() != expected:
                            unresolved.append((lock.get("case_id"), key))
        if domain in {"batteries", "catalysis"}:
            count = LEGACY
        else:
            count = choose(freeze.get("case_count"), closure.get("case_count"), len(by_id))
        direct_references = {
            key: {"path": freeze[key], "exists": (ROOT / freeze[key]).is_file()}
            for key in ("source_lock", "generated_output")
            if isinstance(freeze.get(key), str)
        }
        limitations = choose(
            freeze.get("known_limitations"), freeze.get("limitations"), closure.get("limitations"),
            [freeze["provider_evaluation_caveat"]] if freeze.get("provider_evaluation_caveat") else None,
            [f"raw_provider_readiness: {freeze['raw_provider_readiness']}"] if freeze.get("raw_provider_readiness") else None,
            [],
        )
        domains.append({
            "domain": domain, "version": "v1", "scientific_status": "deterministically_closed" if domain == "biomaterials" else "frozen_deterministic_scope",
            "freeze_status": "pending_live_provider_gate" if domain == "biomaterials" else "frozen",
            "benchmark_case_count": count,
            "canonical_outputs": canonical if canonical is not None else LEGACY,
            "experiments": experiments if experiments is not None else LEGACY,
            "calculations": calculations if calculations is not None else LEGACY,
            "invariant_pass_count": inv if inv is not None else LEGACY,
            "contamination": contamination if contamination is not None else LEGACY,
            "live_provider_gate": gate_satisfied if gate_satisfied is not None else LEGACY,
            "qualifying_provider_model": qualifying, "freeze_commit": FREEZE_COMMITS.get(domain),
            "freeze_manifest": rel(freeze_path) if freeze else None,
            "closure_audit": rel(closure_path) if closure else None,
            "source_lock_audit": lock_hash_audit(folder, index),
            "freeze_direct_references": direct_references,
            "reproduction_commands": choose(freeze.get("reproduce"), freeze.get("reproduction_commands")),
            "verified_case_hash_references": len(verified), "unresolved_case_hash_references": unresolved,
            "freeze_blocker": "external_provider_availability" if domain == "biomaterials" else None,
            "known_limitations": limitations,
        })
    return domains, registry, safety


def measure(yes: int, denominator: int) -> dict:
    return {"numerator": yes, "denominator": denominator, "rate": yes / denominator if denominator else None}


def safety_dimensions(by_domain: dict) -> dict:
    aliases = {
        "evidence_violations": ("evidence_violations", "evidence"),
        "ownership_contamination": ("ownership_contamination", "ownership"),
        "cross_record_leakage": ("cross_record_leakage",),
        "analytics_contamination": ("analytics_contamination", "analytics", "archive_analytics"),
        "graph_contamination": ("graph_contamination", "graph"),
        "unsupported_derived_value_admission": (),
        "review_leakage": (),
        "negative_routing_contamination": (),
    }
    dimensions = {}
    for dimension, keys in aliases.items():
        values = {}
        for domain, item in by_domain.items():
            reported = item.get("reported") or {}
            found = next((reported[k] for k in keys if k in reported), None)
            if isinstance(found, list):
                found = len(found)
            values[domain] = {"value": found, "basis_kind": item["basis_kind"] if found is not None else None}
        dimensions[dimension] = values
    return dimensions


def provider_group_summary(runs: list[dict]) -> dict:
    known = [r for r in runs if isinstance(r.get("payload_returned"), bool)]
    payload = [r for r in known if r["payload_returned"]]
    schema = [r for r in payload if isinstance(r.get("schema_valid"), bool)]
    admission = [r for r in payload if isinstance(r.get("canonical_admission"), bool)]
    normalized_schema = [r for r in payload if isinstance(r.get("normalized_schema_valid"), bool)]
    normalized_admission = [r for r in payload if isinstance(r.get("normalized_canonical_admission"), bool)]
    return {
        "runs": len(runs), "attempts": sum(r.get("attempt_count") or 0 for r in runs),
        "cases": sorted({r["case"] for r in runs}),
        "exact_models": sorted({r["exact_model"] for r in runs if r.get("exact_model")}),
        "payload_availability": measure(len(payload), len(known)),
        "no_payload_runs": len(known) - len(payload),
        "raw_scientifically_scored_payload_runs": sum(r.get("raw_scientific_score") is not None for r in payload),
        "schema_validity_observed": measure(sum(r["schema_valid"] is True for r in schema), len(schema)),
        "canonical_admission_observed": measure(sum(r["canonical_admission"] is True for r in admission), len(admission)),
        "normalized_schema_validity_observed": measure(sum(r["normalized_schema_valid"] is True for r in normalized_schema), len(normalized_schema)),
        "normalized_admission_observed": measure(sum(r["normalized_canonical_admission"] is True for r in normalized_admission), len(normalized_admission)),
        "deterministic_comparison_available_runs": sum(r.get("deterministic_comparison") is not None for r in runs),
    }


def enrich_frozen_normalization_runs(runs: list[dict], manifest: dict) -> None:
    """Join already-frozen normalization metadata by exact run identity."""
    frozen = {
        (row.get("case_id"), row.get("run_id"), row.get("exact_model")): row
        for row in manifest.get("provider_runs", [])
        if isinstance(row, dict)
    }
    for run in runs:
        row = frozen.get((run.get("case"), run.get("run_id"), run.get("exact_model")))
        if not row:
            continue
        run["normalized_scientific_score"] = row.get("normalized_scientific_score")
        run["normalized_schema_valid"] = row.get("normalized_schema_valid")
        run["normalized_canonical_admission"] = row.get("normalized_canonical_admission")
        run["normalization_version"] = row.get("normalization_version")
        run["normalization_source"] = "benchmark/semiconductors_v1/freeze_manifest.json"
        run["normalization_artifact_path"] = row.get("normalization_artifact_path")
        run["normalization_artifact_hashes"] = row.get("normalization_artifact_hashes")


def providers() -> dict:
    package = build_provider_history()
    current = package["runs"]
    historic = read(BENCHMARK / "provider_audit" / "provider_history.json").get("runs", [])
    by_report = {r["report_path"]: r for r in historic}
    by_report.update({r["report_path"]: r for r in current})
    runs = sorted(by_report.values(), key=lambda r: (r["domain"], r["case"], r.get("run_id") or "", r["report_path"]))
    enrich_frozen_normalization_runs(
        [r for r in runs if r["domain"] == "semiconductors"],
        read(BENCHMARK / "semiconductors_v1" / "freeze_manifest.json"),
    )
    for run in runs:
        if run.get("payload_returned") is False:
            run["raw_scientific_score"] = None
            run["schema_valid"] = None
            run["canonical_admission"] = None
        run["stage_comparison"] = {
            "deterministic_pipeline": run.get("deterministic_comparison"),
            "raw_provider": run.get("raw_scientific_score") if run.get("payload_returned") is True else None,
            "normalized_provider": run.get("normalized_scientific_score") if run.get("payload_returned") is True else None,
            "normalized_schema_valid": run.get("normalized_schema_valid") if run.get("payload_returned") is True else None,
            "normalized_canonical_admission": run.get("normalized_canonical_admission") if run.get("payload_returned") is True else None,
            "canonical_admission": run.get("canonical_admission") if run.get("payload_returned") is True else None,
        }
    payload_known = [r for r in runs if r.get("payload_returned") is not None]
    payload_yes = [r for r in runs if r.get("payload_returned") is True]
    schema_known = [r for r in payload_yes if isinstance(r.get("schema_valid"), bool)]
    admission_known = [r for r in payload_yes if isinstance(r.get("canonical_admission"), bool)]
    by_domain = {
        domain: provider_group_summary([r for r in runs if r["domain"] == domain])
        for domain in sorted({r["domain"] for r in runs})
    }
    return {
        "method": "existing_report_metadata_only_no_provider_calls", "run_count": len(runs),
        "historical_history_count": len(historic), "current_report_count": len(current),
        "models": sorted({r.get("exact_model") for r in runs if r.get("exact_model")}),
        "by_domain": by_domain,
        "metrics": {
            "payload_availability": measure(len(payload_yes), len(payload_known)),
            "schema_validity_given_payload_and_observed_schema": measure(sum(r["schema_valid"] is True for r in schema_known), len(schema_known)),
            "canonical_admission_given_payload_and_observed_admission": measure(sum(r["canonical_admission"] is True for r in admission_known), len(admission_known)),
            "raw_exact_value_recovery": {"numerator": None, "denominator": None, "rate": None, "reason": "heterogeneous_score_contracts_not_safe_to_pool"},
            "repair_success": {"numerator": None, "denominator": None, "rate": None, "reason": "repair_outcome_not_standardized_across_legacy_reports"},
            "normalization_success": {"numerator": None, "denominator": None, "rate": None, "reason": "normalization_outcome_not_standardized_across_legacy_reports"},
            "evidence_completeness": {"numerator": None, "denominator": None, "rate": None, "reason": "evidence_contracts_differ_by_domain"},
        },
        "runs": runs,
    }


def write_json(name: str, value) -> None:
    (HERE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    index = hash_index()
    domains, registry, safety = build_domain_and_registry(index)
    provider = providers()
    write_json("domain_status.json", {"domains": domains, "legacy_metric_marker": LEGACY})
    write_json("benchmark_registry.json", {"cases": registry, "case_count": len(registry), "scope": "manifest_case_records_only; legacy cases not standardized"})
    write_json("provider_matrix.json", provider)
    write_json("scientific_safety.json", {
        "by_domain": safety, "dimensions": safety_dimensions(safety), "global_aggregate": None,
        "reason": "legacy_and_modern_audit_schemas_not_comparable; missing_dimensions_are_not_zero",
    })
    write_json("worktree_audit.json", worktree())
    lines = ["# Ten-domain scientific status", "", "| Domain | Freeze | Cases | Outputs | Experiments | Calculations | Invariants | Live gate |", "|---|---|---:|---:|---:|---:|---:|---|"]
    for d in domains:
        lines.append("| " + " | ".join(str(d[k]) for k in ("domain", "freeze_status", "benchmark_case_count", "canonical_outputs", "experiments", "calculations", "invariant_pass_count", "live_provider_gate")) + " |")
    lines += ["", f"Registry: {len(registry)} manifest case records. Legacy Batteries/Catalysis are not represented by standardized case manifests and are excluded from this count.", "", "Provider scores are run/model specific. No-payload outcomes have null scientific scores, not zero.", ""]
    (HERE / "domain_status.md").write_text("\n".join(lines), encoding="utf-8")
    known_outputs = [d["canonical_outputs"] for d in domains if isinstance(d["canonical_outputs"], int)]
    known_experiments = [d["experiments"] for d in domains if isinstance(d["experiments"], int)]
    known_calculations = [d["calculations"] for d in domains if isinstance(d["calculations"], int)]
    available = provider["metrics"]["payload_availability"]
    sem_normalized = provider["by_domain"].get("semiconductors", {})
    lock_verified = sum(d["source_lock_audit"]["verified_hash_references"] for d in domains)
    lock_unresolved = sum(len(d["source_lock_audit"]["unresolved_hash_references"]) for d in domains)
    case_verified = sum(d["verified_case_hash_references"] for d in domains)
    summary = [
        "# System consolidation snapshot", "",
        "This is an offline metadata audit. It does not change frozen gold, call a provider, or freeze Biomaterials.", "",
        f"- Ten domains: nine frozen, Biomaterials deterministically closed and live-gate pending.",
        f"- Standardized manifest cases: {len(registry)} across eight modern domains; Batteries and Catalysis have legacy, nonstandardized counts.",
        f"- Canonical outputs: {sum(known_outputs)} across {len(known_outputs)}/10 domains with complete domain totals. Experiments: {sum(known_experiments)} across {len(known_experiments)}/10; calculations: {sum(known_calculations)} across {len(known_calculations)}/10. These are coverage-limited sums, not ten-domain totals.",
        f"- Existing metadata-only provider reports: {provider['run_count']} across {len({r['domain'] for r in provider['runs']})}/10 domains. Payload availability: {available['numerator']}/{available['denominator']} known outcomes. No-payload runs have null scientific scores.",
        f"- Modern source-lock hash references: {lock_verified} matched local bytes, {lock_unresolved} unresolved; manifest case hash references: {case_verified} matched local bytes. Batteries/Catalysis have no standardized source-lock files in this scan.",
        "- Raw scientific scores, repair success, normalization success, and evidence completeness cannot be pooled across heterogeneous historical contracts. Per-run stage comparisons are in provider_matrix.json.",
        f"- Semiconductor frozen normalization subset: schema-valid {sem_normalized.get('normalized_schema_validity_observed', {}).get('numerator')}/{sem_normalized.get('normalized_schema_validity_observed', {}).get('denominator')}, canonically admitted {sem_normalized.get('normalized_admission_observed', {}).get('numerator')}/{sem_normalized.get('normalized_admission_observed', {}).get('denominator')}. These are model-specific subset counts, not cross-domain rates.",
        "- Scientific safety is recorded by domain with observed-vs-expected basis; no unsupported global zero-contamination total is asserted.",
        "- Biomaterials: 8/8 cases, 158/158 outputs, 40/40 invariants, six pinned model runs/16 attempts, zero payloads. BIO-BIOACT-B was not sent. Retry only after material provider/quota/model change or intentional alternative-provider activation.",
        "", "## Evidence", "",
        "See domain_status.json, benchmark_registry.json, provider_matrix.json, scientific_safety.json, and worktree_audit.json. Hash matches identify locally present source/gold bytes; legacy domains and nonstandardized fields remain explicitly unverified. The current full-suite regression result is reported separately after tests finish.", "",
    ]
    (HERE / "system_summary.md").write_text("\n".join(summary), encoding="utf-8")
    print(f"{len(domains)} domains, {len(registry)} manifest cases, {provider['run_count']} provider reports")


if __name__ == "__main__":
    main()
