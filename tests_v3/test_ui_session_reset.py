from synthex_platform.ui_session import clear_research_workspace


def test_clear_research_workspace_removes_current_analysis_state_only():
    state = {
        "synthex_pdf_batch": ["paper.pdf"],
        "synthex_batch_archives": [{"archive": 1}],
        "synthex_batch_status": [{"status": "complete"}],
        "synthex_last_archive": {"archive": 1},
        "synthex_last_route": "catalysis",
        "synthex_batch_inspect": "1. Paper",
        "synthex_batch_include_quarantined": True,
        "synthex_explorer_scope": "All successful papers",
        "synthex_explorer_include_quarantined": True,
        "synthex_explorer_search": "Ni",
        "synthex_explorer_estimated": "All",
        "synthex_explorer_results_table": {"selection": [0]},
        "filter_metric": ["conversion"],
        "synthex_explorer_filter_domain": ["catalysis"],
        "synthex_workspace": "Explore Results",
        "synthex_provider_health": [{"model": "gemini"}],
        "synthex_saved_discovery_candidates": ["keep-me"],
    }

    removed = clear_research_workspace(state)

    assert "synthex_pdf_batch" in removed
    assert "filter_metric" in removed
    assert "synthex_explorer_filter_domain" in removed
    assert "synthex_last_archive" not in state
    assert "synthex_batch_archives" not in state
    assert "synthex_explorer_search" not in state
    assert "filter_metric" not in state
    assert "synthex_workspace" in state
    assert state["synthex_workspace"] == "Explore Results"
    assert state["synthex_provider_health"] == [{"model": "gemini"}]
    assert state["synthex_saved_discovery_candidates"] == ["keep-me"]


def test_clear_research_workspace_is_idempotent():
    state = {"synthex_workspace": "Analyze Paper"}
    assert clear_research_workspace(state) == []
    assert clear_research_workspace(state) == []
