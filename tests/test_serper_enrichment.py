from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.models import SourceRecord
from synthex_platform.retrieval import MetadataEnricher, SerperClient


def _archive():
    return SynthexArchive(
        metadata=ArchiveMetadata(archive_id="arc-test", domain="batteries"),
        sources=[SourceRecord(source_id="src-test", title="A Test Battery Paper", authors=["A. Author"])],
    )


def test_serper_cache_avoids_second_network_call(tmp_path: Path):
    payload = {"organic": [{"title": "A Test Battery Paper", "link": "https://doi.org/10.1234/test.2026", "snippet": "Published 2026"}]}
    fake = Mock()
    fake.raise_for_status.return_value = None
    fake.json.return_value = payload
    client = SerperClient(api_key="dummy", cache_dir=tmp_path, query_budget=10)

    with patch("synthex_platform.retrieval.serper_client.requests.post", return_value=fake) as post:
        first = client.search('"A Test Battery Paper" DOI')
        second = client.search('"A Test Battery Paper" DOI')

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert post.call_count == 1
    assert client.usage()["network_queries"] == 1


def test_metadata_enrichment_only_fills_missing_bibliographic_fields(tmp_path: Path):
    payload = {"organic": [{
        "title": "A Test Battery Paper",
        "link": "https://doi.org/10.1234/test.2026",
        "snippet": "Journal of Batteries, 2026. No scientific values are used from this snippet.",
    }]}
    fake = Mock()
    fake.raise_for_status.return_value = None
    fake.json.return_value = payload
    client = SerperClient(api_key="dummy", cache_dir=tmp_path, query_budget=10)

    with patch("synthex_platform.retrieval.serper_client.requests.post", return_value=fake):
        archive = MetadataEnricher(client=client).enrich_archive(_archive())

    src = archive.sources[0]
    assert src.doi == "10.1234/test.2026"
    assert src.url == "https://doi.org/10.1234/test.2026"
    assert src.year == 2026
    retrieval = [p for p in archive.domain_payloads if p.domain == "retrieval"]
    assert len(retrieval) == 1
    assert "scientific" in retrieval[0].values["policy"]


def test_existing_pdf_metadata_is_not_overwritten(tmp_path: Path):
    a = _archive()
    a.sources[0].doi = "10.9999/original"
    a.sources[0].url = "https://publisher.example/original"
    a.sources[0].year = 2025
    client = SerperClient(api_key="dummy", cache_dir=tmp_path, query_budget=10)
    archive = MetadataEnricher(client=client).enrich_archive(a)
    assert archive.sources[0].doi == "10.9999/original"
    assert archive.sources[0].url == "https://publisher.example/original"
    assert archive.sources[0].year == 2025
    assert client.usage()["network_queries"] == 0
