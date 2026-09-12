from __future__ import annotations

"""Legacy-compatible search entry point backed by the V3.4 Serper client.

For the V3 platform, prefer synthex_platform.retrieval. This module remains so
older Synthex code can keep importing search_papers().
"""

from synthex_platform.retrieval import SerperClient


def search_papers(category: str, num_results: int = 5, sensor_focus: str | None = None) -> list[dict]:
    focus = f" {sensor_focus}" if sensor_focus else ""
    query = f"{category}{focus} materials science PDF research paper"
    response = SerperClient().search(query, num=num_results)
    results = []
    for item in (response.data.get("organic", []) or [])[:num_results]:
        results.append({
            "title": item.get("title"),
            "url": item.get("link"),
            "snippet": item.get("snippet"),
            "cache_hit": response.cache_hit,
        })
    return results
