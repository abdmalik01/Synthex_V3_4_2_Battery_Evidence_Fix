from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmark" / "corrosion_v1" / "build_gold_candidates.py"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_gold_candidate_harvester_is_offline_and_never_mines_holdout():
    source = _source()
    assert "External calls: 0" in source
    assert '"CORR-HOLDOUT-I"' in source
    assert '"holdout_not_mined"' in source
    lowered = source.casefold()
    assert "gemini" not in lowered
    assert "requests." not in lowered
    assert "http://" not in lowered
    assert "https://" not in lowered


def test_candidate_harvester_marks_snippets_as_not_gold_and_requires_manual_review():
    source = _source()
    tree = ast.parse(source)
    assert tree is not None
    assert '"candidate_snippets_are_not_gold": True' in source
    assert '"manual_source_review_required": True' in source
    assert '"no_llm_generated_gold": True' in source
    assert '"no_unit_or_reference_electrode_conversion": True' in source


def test_candidate_terms_cover_every_scored_corrosion_role():
    namespace: dict = {}
    module = ast.parse(_source())
    assignment = next(
        node for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "ROLE_TERMS" for target in node.targets)
    )
    role_terms = ast.literal_eval(assignment.value)
    assert set(role_terms) == {
        "bare_alloy_polarization",
        "coating_surface_treatment",
        "corrosion_inhibitor",
        "eis_heavy",
        "immersion_weight_loss",
        "computational_corrosion",
        "review_contamination_control",
        "non_corrosion_negative_control",
    }
    assert all(role_terms[role] for role in role_terms)
