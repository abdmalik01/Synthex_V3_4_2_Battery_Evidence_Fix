from types import SimpleNamespace

from synthex_platform.ui_empty_state import archive_empty_state


def _archive(values, domain="catalysis"):
    return SimpleNamespace(
        metadata=SimpleNamespace(domain=domain),
        domain_payloads=[SimpleNamespace(domain=domain, values=values)],
    )


def test_review_archive_explains_intentional_empty_results():
    archive = _archive({
        "validated_document": {
            "paper_types": ["review"],
            "extraction_notes": ["No original focal experimental or computational dataset was created."],
        },
        "admissibility_audit": {
            "canonical_admission_count": 0,
            "quarantined_objects_or_values": 0,
        },
    })
    state = archive_empty_state(archive, result_count=0)
    assert state["kind"] == "review_no_focal_data"
    assert "review article" in state["message"]
    assert "cited literature" in state["message"]


def test_quarantined_only_archive_points_researcher_to_review_toggle():
    archive = _archive({
        "validated_document": {"paper_types": ["experimental"]},
        "admissibility_audit": {
            "canonical_admission_count": 0,
            "quarantined_objects_or_values": 3,
        },
    })
    state = archive_empty_state(archive, result_count=0)
    assert state["kind"] == "quarantined_only"
    assert state["quarantined"] == 3
    assert "Include quarantined" in state["message"]


def test_nonempty_results_need_no_empty_state():
    archive = _archive({"validated_document": {"paper_types": ["review"]}})
    assert archive_empty_state(archive, result_count=2) is None
