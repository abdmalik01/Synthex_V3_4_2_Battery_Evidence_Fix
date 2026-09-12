from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv(override=True)


@dataclass
class SerperResponse:
    query: str
    data: dict[str, Any]
    cache_hit: bool
    network_query_number: int | None = None


class SerperClient:
    """Small, quota-conscious Serper client with persistent local caching.

    Synthex uses Serper for discovery/metadata enrichment only. Search snippets are
    never treated as authoritative scientific measurements.
    """

    endpoint = "https://google.serper.dev/search"

    def __init__(
        self,
        api_key: str | None = None,
        cache_dir: str | Path = "data/search_cache",
        timeout: int = 30,
        query_budget: int | None = None,
    ):
        self.api_key = api_key or os.getenv("SERPER_API_KEY")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.query_budget = int(query_budget or os.getenv("SERPER_QUERY_BUDGET", "2500"))
        self.stats_path = self.cache_dir / "stats.json"

    def _cache_key(self, query: str, num: int) -> str:
        payload = json.dumps({"q": query, "num": num}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _read_stats(self) -> dict[str, int]:
        if not self.stats_path.exists():
            return {"network_queries": 0}
        try:
            data = json.loads(self.stats_path.read_text(encoding="utf-8"))
            return {"network_queries": int(data.get("network_queries", 0))}
        except Exception:
            return {"network_queries": 0}

    def _write_stats(self, stats: dict[str, int]) -> None:
        self.stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    def usage(self) -> dict[str, int]:
        used = self._read_stats()["network_queries"]
        return {
            "network_queries": used,
            "configured_budget": self.query_budget,
            "remaining_local_budget": max(self.query_budget - used, 0),
        }

    def search(self, query: str, num: int = 5, use_cache: bool = True) -> SerperResponse:
        query = " ".join(query.split()).strip()
        if not query:
            raise ValueError("Serper query cannot be empty.")
        num = max(1, min(int(num), 10))
        cache_path = self.cache_dir / f"{self._cache_key(query, num)}.json"

        if use_cache and cache_path.exists():
            return SerperResponse(
                query=query,
                data=json.loads(cache_path.read_text(encoding="utf-8")),
                cache_hit=True,
            )

        if not self.api_key:
            raise ValueError("SERPER_API_KEY is missing. Add it to .env to enable search-assisted enrichment.")

        stats = self._read_stats()
        if stats["network_queries"] >= self.query_budget:
            raise RuntimeError(
                f"Local Serper query budget exhausted ({self.query_budget}). "
                "Increase SERPER_QUERY_BUDGET only if your actual Serper plan permits it."
            )

        response = requests.post(
            self.endpoint,
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            json={"q": query, "num": num},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        stats["network_queries"] += 1
        self._write_stats(stats)

        return SerperResponse(
            query=query,
            data=data,
            cache_hit=False,
            network_query_number=stats["network_queries"],
        )
