"""Local-only readiness check. This module has no provider client or transmit call."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction.domain_extractor import DomainProviderExtractor
from synthex_platform.extraction.source_context import build_source_bundle

from .offline_recovery import LOCKS, ROOT


REPO = ROOT.parents[1]
DISCOVERY_DIR = REPO / "output/biomaterials_v1/provider_runs/model_discovery"
AUDIT_DIR = REPO / "output/biomaterials_v1/provider_runs"
CANDIDATES = ("models/gemini-3.8-flash", "models/gemini-3.5-flash", "models/gemini-2.5-flash")
LIVE_CASES = ("BIO-GOLD-A", "BIO-BIOACT-B")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(discovery_path: Path | None = None, *, candidates: tuple[str, ...] | None = None) -> dict:
    if discovery_path is None:
        matches = sorted(DISCOVERY_DIR.glob("*.json"))
        if not matches:
            raise ValueError("No newly discovered exact Gemini model list")
        discovery_path = matches[-1]
    discovery_path = discovery_path.resolve()
    if discovery_path.parent != DISCOVERY_DIR.resolve():
        raise ValueError("Discovery artifact must be in the Biomaterials model_discovery directory")
    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    eligible = {item["model_id"] for item in discovery["eligible_general_text_models"]}
    selected = CANDIDATES if candidates is None else candidates
    if not 1 <= len(selected) <= 3 or len(set(selected)) != len(selected):
        raise ValueError("One to three distinct exact Gemini models required")
    if any(not item.startswith("models/gemini-") or item.endswith("-latest") for item in selected):
        raise ValueError("Exact, non-alias Gemini model IDs required")
    if not set(selected) <= eligible:
        raise ValueError("Selected exact models absent from discovery artifact")
    # Build the production prompt without constructing a provider adapter/client.
    prompt_builder = object.__new__(DomainProviderExtractor)
    prompt_builder.registry = DomainRegistry()
    inputs = []
    for case in LIVE_CASES:
        lock = LOCKS[case]
        pdf = ROOT / lock["pdf"]
        gold = ROOT / lock["gold"]
        if _sha(pdf.read_bytes()) != lock["pdf_sha256"] or _sha(gold.read_bytes()) != lock["gold_sha256"]:
            raise ValueError(f"Locked source/gold changed: {case}")
        bundle = build_source_bundle(pdf, enable_ocr=False, include_figures=False)
        source_text = bundle.page_marked_text()
        # Gold bytes are hash-checked, never interpolated into the prompt.
        prompt = prompt_builder.build_prompt(source_text, "biomaterials", source_bundle=bundle)
        inputs.append({"case_id": case, "pdf_sha256": lock["pdf_sha256"], "gold_sha256": lock["gold_sha256"],
                       "source_text_sha256": _sha(source_text.encode("utf-8")),
                       "prompt_sha256": _sha(prompt.encode("utf-8")),
                       "gold_in_prompt": False, "gold_used": "hash_verification_only"})
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    return {"provider": "gemini", "authorization_status": "NOT_EVALUATED_BY_LOCAL_PREPARATION",
            "source_transmitted_by_preparation": False,
            "discovery_artifact": discovery_path.relative_to(REPO).as_posix(),
            "discovery_sha256": _sha(discovery_path.read_bytes()), "candidate_exact_models": list(selected),
            "maximum_transient_attempts_per_model": 3,
            "raw_before_validation_recorder": "synthex_platform.benchmarks.provider_artifacts.ProviderArtifactRecorder",
            "audit_directory": AUDIT_DIR.relative_to(REPO).as_posix(), "inputs": inputs}


if __name__ == "__main__":
    plan = prepare()
    path = ROOT / "live_preparation.json"
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"plan": str(path), "models": plan["candidate_exact_models"],
                      "source_transmitted_by_preparation": False}))
