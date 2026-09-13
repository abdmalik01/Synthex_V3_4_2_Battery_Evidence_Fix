from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import requests

from synthex_platform.retrieval.discovery import (
    DISCOVERY_RESULTS_KEY,
    DISCOVERY_SELECTED_KEY,
    DiscoveryError,
    build_discovery_query,
    clear_discovery_results,
    clear_saved_discovery_candidates,
    current_discovery_results,
    discover_papers,
    initialize_discovery_state,
    remove_discovery_candidate,
    save_discovery_candidate,
    saved_discovery_candidates,
    store_discovery_results,
)
from synthex_platform.retrieval.serper_client import SerperResponse
from synthex_platform.storage import JsonlArchiveStore


class FakeClient:
    def __init__(self, response: SerperResponse | Exception):
        self.response = response
        self.queries: list[tuple[str, int]] = []

    def search(self, query: str, num: int = 5, use_cache: bool = True) -> SerperResponse:
        self.queries.append((query, num))
        if isinstance(self.response, Exception):
            raise self.response
        return replace(self.response, query=query)

    def usage(self) -> dict[str, int]:
        return {"network_queries": 7, "configured_budget": 10, "remaining_local_budget": 3}


def _response(*, cache_hit: bool = False, data=None) -> SerperResponse:
    return SerperResponse(
        query="NiFe LDH OER catalyst",
        data=data if data is not None else {"organic": [{
            "title": "NiFe LDH catalyst paper",
            "link": "https://doi.org/10.1234/nife.2026",
            "snippet": "A discovery snippet that must not become scientific evidence.",
        }]},
        cache_hit=cache_hit,
        network_query_number=None if cache_hit else 7,
    )


def test_discovery_query_construction_and_result_provenance():
    client = FakeClient(_response())
    result = discover_papers("  NiFe   LDH OER catalyst ", focus="Catalysis and electrocatalysis", num_results=4, client=client)

    assert client.queries == [("NiFe LDH OER catalyst Catalysis and electrocatalysis", 4)]
    assert result.query == "NiFe LDH OER catalyst Catalysis and electrocatalysis"
    assert result.usage["remaining_local_budget"] == 3
    candidate = result.candidates[0]
    assert candidate.title == "NiFe LDH catalyst paper"
    assert candidate.cache_hit is False
    assert candidate.network_query_number == 7
    assert candidate.doi == "10.1234/nife.2026"
    assert candidate.doi_provenance == "direct_doi_url"
    assert candidate.year is None
    assert candidate.scientific_evidence is False


def test_cached_result_metadata_is_preserved():
    result = discover_papers("NiFe LDH OER catalyst", client=FakeClient(_response(cache_hit=True)))

    assert result.cache_hit is True
    assert result.network_query_number is None
    assert result.candidates[0].cache_hit is True
    assert result.candidates[0].network_query_number is None


def test_malformed_provider_response_is_rejected_safely():
    with pytest.raises(DiscoveryError, match="unexpected provider response"):
        discover_papers("NiFe LDH", client=FakeClient(_response(data=["not an object"])))

    with pytest.raises(DiscoveryError, match="malformed search results"):
        discover_papers("NiFe LDH", client=FakeClient(_response(data={"organic": "not a list"})))


def test_discovery_error_messages_are_concise():
    with pytest.raises(DiscoveryError, match="SERPER_API_KEY"):
        discover_papers("ZnO NiO gas sensing", client=FakeClient(ValueError("SERPER_API_KEY is missing")))
    with pytest.raises(DiscoveryError, match="budget is exhausted"):
        discover_papers("ZnO NiO gas sensing", client=FakeClient(RuntimeError("budget exhausted")))
    with pytest.raises(DiscoveryError, match="timed out"):
        discover_papers("ZnO NiO gas sensing", client=FakeClient(requests.Timeout("slow provider")))


def test_empty_query_is_rejected_before_provider_call():
    with pytest.raises(ValueError, match="Enter a paper"):
        build_discovery_query("   ")


def test_session_results_persist_until_explicit_clear():
    state = {}
    initialize_discovery_state(state)
    result = discover_papers("LiFePO4 cathode synthesis", client=FakeClient(_response(cache_hit=True)))

    store_discovery_results(state, result)
    assert current_discovery_results(state) == result
    clear_discovery_results(state)
    assert state[DISCOVERY_RESULTS_KEY] is None
    assert current_discovery_results(state) is None


def test_saved_candidate_survives_result_clear_and_can_be_removed():
    state = {}
    initialize_discovery_state(state)
    result = discover_papers("CO2RR Cu catalyst", client=FakeClient(_response()))
    candidate = result.candidates[0]

    assert save_discovery_candidate(state, candidate) is True
    assert save_discovery_candidate(state, candidate) is False
    clear_discovery_results(state)
    assert saved_discovery_candidates(state) == [candidate]
    remove_discovery_candidate(state, candidate.candidate_id)
    assert saved_discovery_candidates(state) == []
    clear_saved_discovery_candidates(state)
    assert state[DISCOVERY_SELECTED_KEY] == []


def test_discovery_metadata_cannot_create_evidence_or_canonical_archive(tmp_path: Path):
    state = {}
    initialize_discovery_state(state)
    result = discover_papers("LiFePO4 cathode synthesis", client=FakeClient(_response()))
    candidate = result.candidates[0]

    store_discovery_results(state, result)
    save_discovery_candidate(state, candidate)

    assert "evidence" not in candidate.model_dump()
    assert candidate.scientific_evidence is False
    archive_path = tmp_path / "archives.jsonl"
    store = JsonlArchiveStore(archive_path)
    assert store.count() == 0
    assert not archive_path.exists()
