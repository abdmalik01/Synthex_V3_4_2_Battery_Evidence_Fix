from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.core.models import DomainPayload
from .serper_client import SerperClient

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _norm_title(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _title_similarity(a: str | None, b: str | None) -> float:
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _extract_doi(*parts: str | None) -> str | None:
    for part in parts:
        if not part:
            continue
        m = DOI_RE.search(part)
        if m:
            return m.group(0).rstrip(".,);]")
    return None


def _result_candidates(data: dict[str, Any], paper_title: str) -> list[dict[str, Any]]:
    out = []
    for item in data.get("organic", []) or []:
        title = item.get("title")
        link = item.get("link")
        snippet = item.get("snippet")
        out.append({
            "title": title,
            "url": link,
            "snippet": snippet,
            "doi": _extract_doi(link, snippet, title),
            "title_similarity": round(_title_similarity(paper_title, title), 3),
        })
    out.sort(key=lambda x: x["title_similarity"], reverse=True)
    return out


class MetadataEnricher:
    """Conservative bibliographic enrichment from Serper results.

    Only missing bibliographic fields can be filled. No scientific measurement,
    synthesis condition, performance number, or material property is populated
    from a search snippet.
    """

    def __init__(self, client: SerperClient | None = None, min_title_similarity: float = 0.72):
        self.client = client or SerperClient()
        self.min_title_similarity = min_title_similarity

    def enrich_archive(self, archive: SynthexArchive, find_supplementary: bool = False) -> SynthexArchive:
        if not archive.sources:
            return archive
        source = archive.sources[0]
        if not source.title:
            archive.quality.semantic_warnings.append(
                "Search-assisted enrichment skipped because the extracted source has no title."
            )
            return archive

        needs_metadata = not source.doi or not source.url or not source.year
        enrichment: dict[str, Any] = {
            "provider": "Serper",
            "policy": "bibliographic/discovery enrichment only; search snippets are not scientific evidence",
            "fields_applied": {},
            "queries": [],
            "candidates": [],
            "supplementary_candidates": [],
        }

        if needs_metadata:
            author_hint = source.authors[0] if source.authors else ""
            query = f'"{source.title}" {author_hint} DOI'.strip()
            response = self.client.search(query, num=5)
            candidates = _result_candidates(response.data, source.title)
            enrichment["queries"].append({
                "purpose": "metadata",
                "query": query,
                "cache_hit": response.cache_hit,
            })
            enrichment["candidates"] = candidates

            best = candidates[0] if candidates else None
            if best and best["title_similarity"] >= self.min_title_similarity:
                # Apply only missing bibliographic values. Keep the PDF/Gemini value when present.
                if not source.doi and best.get("doi"):
                    source.doi = best["doi"]
                    enrichment["fields_applied"]["doi"] = {
                        "value": source.doi,
                        "source_url": best.get("url"),
                        "title_similarity": best["title_similarity"],
                    }
                if not source.url and best.get("url"):
                    source.url = best["url"]
                    enrichment["fields_applied"]["url"] = {
                        "value": source.url,
                        "title_similarity": best["title_similarity"],
                    }
                if not source.year:
                    year_match = YEAR_RE.search(" ".join(filter(None, [best.get("snippet"), best.get("title")])))
                    if year_match:
                        source.year = int(year_match.group(1))
                        enrichment["fields_applied"]["year"] = {
                            "value": source.year,
                            "source_url": best.get("url"),
                            "title_similarity": best["title_similarity"],
                        }

        if find_supplementary:
            query = f'"{source.title}" supplementary information OR supporting information'
            response = self.client.search(query, num=5)
            enrichment["queries"].append({
                "purpose": "supplementary_discovery",
                "query": query,
                "cache_hit": response.cache_hit,
            })
            enrichment["supplementary_candidates"] = _result_candidates(response.data, source.title)

        enrichment["usage"] = self.client.usage()
        archive.domain_payloads.append(DomainPayload(
            domain="retrieval",
            schema_version="1.0.0",
            tags=["serper", "search_assisted"],
            values=enrichment,
        ))
        return archive
