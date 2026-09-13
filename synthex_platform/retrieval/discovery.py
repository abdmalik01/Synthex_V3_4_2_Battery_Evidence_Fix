from __future__ import annotations

"""Typed, non-scientific paper-discovery records.

Discovery candidates deliberately do not use ``Evidence`` or archive models.
They are session-scoped navigation metadata that can help a researcher locate a
paper; an uploaded PDF and its ``SourceBundle`` remain the scientific source.
"""

from datetime import datetime, timezone
import hashlib
import re
from typing import Any, MutableMapping, Protocol
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, ConfigDict, Field

from .serper_client import SerperClient, SerperResponse


DISCOVERY_RESULTS_KEY = "synthex_discovery_results"
DISCOVERY_SELECTED_KEY = "synthex_discovery_selected"
DISCOVERY_USAGE_KEY = "synthex_discovery_usage"
DISCOVERY_QUERY_KEY = "synthex_discovery_query"

DOI_URL_RE = re.compile(r"(?:https?://)?(?:dx\.)?doi\.org/(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.I)


class DiscoveryError(RuntimeError):
    """A concise, display-safe paper-discovery failure."""


class DiscoveryClient(Protocol):
    def search(self, query: str, num: int = 5, use_cache: bool = True) -> SerperResponse: ...

    def usage(self) -> dict[str, int]: ...


class DiscoveryCandidate(BaseModel):
    """Unverified bibliographic navigation metadata returned by a provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    title: str
    url: str
    snippet: str | None = None
    doi: str | None = None
    doi_provenance: str | None = None
    year: int | None = None
    year_provenance: str | None = None
    query: str
    provider: str = "Serper"
    cache_hit: bool
    network_query_number: int | None = None
    retrieved_at: datetime
    status: str = "discovery_only_not_scientifically_verified"
    scientific_evidence: bool = False


class DiscoverySearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    candidates: list[DiscoveryCandidate] = Field(default_factory=list)
    cache_hit: bool
    network_query_number: int | None = None
    retrieved_at: datetime
    usage: dict[str, int] = Field(default_factory=dict)


def build_discovery_query(research_query: str, focus: str | None = None) -> str:
    """Build a transparent researcher query without claiming scientific facts."""
    query = " ".join(research_query.split()).strip()
    if not query:
        raise ValueError("Enter a paper, material, reaction, or research-topic query.")
    suffix = " ".join((focus or "").split()).strip()
    return f"{query} {suffix}".strip() if suffix else query


def _safe_http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def _direct_doi(url: str) -> str | None:
    match = DOI_URL_RE.search(url)
    return match.group(1).rstrip(".,);]") if match else None


def _candidate_id(query: str, index: int, title: str, url: str) -> str:
    payload = f"{query}\n{index}\n{title}\n{url}".encode("utf-8")
    return "discovery-" + hashlib.sha256(payload).hexdigest()[:16]


def parse_discovery_response(response: SerperResponse, usage: dict[str, int]) -> DiscoverySearchResult:
    """Turn Serper's organic results into explicitly unverified candidates."""
    if not isinstance(response.data, dict):
        raise DiscoveryError("Paper discovery returned an unexpected provider response.")
    organic = response.data.get("organic", [])
    if not isinstance(organic, list):
        raise DiscoveryError("Paper discovery returned malformed search results.")

    retrieved_at = datetime.now(timezone.utc)
    candidates: list[DiscoveryCandidate] = []
    for index, item in enumerate(organic):
        if not isinstance(item, dict):
            continue
        url = _safe_http_url(item.get("link"))
        if not url:
            continue
        raw_title = item.get("title")
        title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else "Untitled discovery result"
        raw_snippet = item.get("snippet")
        snippet = raw_snippet.strip() if isinstance(raw_snippet, str) and raw_snippet.strip() else None
        doi = _direct_doi(url)
        candidates.append(DiscoveryCandidate(
            candidate_id=_candidate_id(response.query, index, title, url),
            title=title,
            url=url,
            snippet=snippet,
            doi=doi,
            doi_provenance="direct_doi_url" if doi else None,
            query=response.query,
            cache_hit=response.cache_hit,
            network_query_number=response.network_query_number,
            retrieved_at=retrieved_at,
        ))
    return DiscoverySearchResult(
        query=response.query,
        candidates=candidates,
        cache_hit=response.cache_hit,
        network_query_number=response.network_query_number,
        retrieved_at=retrieved_at,
        usage=dict(usage),
    )


def discover_papers(
    research_query: str,
    *,
    focus: str | None = None,
    num_results: int = 5,
    client: DiscoveryClient | None = None,
) -> DiscoverySearchResult:
    """Search through the existing quota-aware Serper client, never raw requests."""
    query = build_discovery_query(research_query, focus)
    active_client = client or SerperClient()
    try:
        response = active_client.search(query, num=num_results)
        return parse_discovery_response(response, active_client.usage())
    except DiscoveryError:
        raise
    except ValueError as exc:
        message = str(exc)
        if "SERPER_API_KEY" in message:
            raise DiscoveryError("Paper discovery needs SERPER_API_KEY in .env.") from exc
        raise DiscoveryError("Paper discovery returned an unexpected provider response.") from exc
    except RuntimeError as exc:
        if "budget exhausted" in str(exc).lower():
            raise DiscoveryError("The local Serper query budget is exhausted. Check SERPER_QUERY_BUDGET and your Serper plan.") from exc
        raise DiscoveryError("Paper discovery is temporarily unavailable. Try again shortly.") from exc
    except requests.Timeout as exc:
        raise DiscoveryError("Paper discovery timed out. Please try again.") from exc
    except (requests.RequestException, OSError, TypeError, KeyError) as exc:
        raise DiscoveryError("Paper discovery could not reach the search provider. Please try again.") from exc


def initialize_discovery_state(state: MutableMapping[str, Any]) -> None:
    state.setdefault(DISCOVERY_RESULTS_KEY, None)
    state.setdefault(DISCOVERY_SELECTED_KEY, [])
    state.setdefault(DISCOVERY_USAGE_KEY, None)
    state.setdefault(DISCOVERY_QUERY_KEY, None)


def store_discovery_results(state: MutableMapping[str, Any], result: DiscoverySearchResult) -> None:
    """Store discovery metadata only; this function cannot create archive records."""
    state[DISCOVERY_RESULTS_KEY] = result.model_dump(mode="json")
    state[DISCOVERY_USAGE_KEY] = dict(result.usage)
    state[DISCOVERY_QUERY_KEY] = result.query


def current_discovery_results(state: MutableMapping[str, Any]) -> DiscoverySearchResult | None:
    raw = state.get(DISCOVERY_RESULTS_KEY)
    return DiscoverySearchResult.model_validate(raw) if raw else None


def saved_discovery_candidates(state: MutableMapping[str, Any]) -> list[DiscoveryCandidate]:
    raw = state.get(DISCOVERY_SELECTED_KEY, [])
    return [DiscoveryCandidate.model_validate(candidate) for candidate in raw]


def save_discovery_candidate(state: MutableMapping[str, Any], candidate: DiscoveryCandidate) -> bool:
    selected = saved_discovery_candidates(state)
    if any(item.candidate_id == candidate.candidate_id for item in selected):
        return False
    state[DISCOVERY_SELECTED_KEY] = [*state.get(DISCOVERY_SELECTED_KEY, []), candidate.model_dump(mode="json")]
    return True


def remove_discovery_candidate(state: MutableMapping[str, Any], candidate_id: str) -> None:
    state[DISCOVERY_SELECTED_KEY] = [
        candidate.model_dump(mode="json")
        for candidate in saved_discovery_candidates(state)
        if candidate.candidate_id != candidate_id
    ]


def clear_discovery_results(state: MutableMapping[str, Any]) -> None:
    """Clear results while retaining explicitly saved candidates for later upload."""
    state[DISCOVERY_RESULTS_KEY] = None
    state[DISCOVERY_USAGE_KEY] = None
    state[DISCOVERY_QUERY_KEY] = None


def clear_saved_discovery_candidates(state: MutableMapping[str, Any]) -> None:
    state[DISCOVERY_SELECTED_KEY] = []
