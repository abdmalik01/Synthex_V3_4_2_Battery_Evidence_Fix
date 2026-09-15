from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = ROOT / "benchmark" / "corrosion_v1"
MANIFEST = CORPUS_ROOT / "corpus_manifest.json"
GOLD_SCAFFOLD = CORPUS_ROOT / "gold_assertions_scaffold.json"
PDF_DIR = CORPUS_ROOT / "corpus pdfs"


def _git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def test_corrosion_stage3_corpus_has_eight_benchmark_papers_plus_one_holdout():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = manifest["entries"]
    assert len(entries) == 9
    assert {entry["id"] for entry in entries} == {
        "CORR-GOLD-A", "CORR-COAT-B", "CORR-INHIB-C", "CORR-EIS-D",
        "CORR-WEIGHT-E", "CORR-DFT-F", "CORR-REVIEW-G", "CORR-NEGATIVE-H",
        "CORR-HOLDOUT-I",
    }
    assert sum(entry["id"] != "CORR-HOLDOUT-I" for entry in entries) == 8


def test_manifest_files_exist_and_match_locked_repository_blob_hashes_and_sizes():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    listed = {entry["filename"] for entry in manifest["entries"]}
    actual = {path.name for path in PDF_DIR.glob("*.pdf")}
    assert actual == listed

    for entry in manifest["entries"]:
        path = PDF_DIR / entry["filename"]
        assert path.stat().st_size == entry["file_size_bytes"]
        assert _git_blob_sha1(path) == entry["git_blob_sha1"]


def test_every_corpus_entry_has_expected_doi_and_title_before_gold_review():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dois = [entry["expected_doi"] for entry in manifest["entries"]]
    assert len(set(dois)) == len(dois)
    assert all(entry["expected_title"].strip() for entry in manifest["entries"])
    assert all(entry["content_verified"] is False for entry in manifest["entries"])
    assert all(entry["sha256"] is None for entry in manifest["entries"])


def test_gold_scaffold_never_claims_unreviewed_numeric_gold_values():
    scaffold = json.loads(GOLD_SCAFFOLD.read_text(encoding="utf-8"))
    assert scaffold["policy"]["no_llm_generated_gold"] is True
    assert scaffold["policy"]["gold_values_must_be_manually_verified_from_pdf"] is True
    assert scaffold["policy"]["holdout_excluded_from_tuning"] is True
    papers = scaffold["papers"]
    assert len(papers) == 9
    assert next(item for item in papers if item["id"] == "CORR-HOLDOUT-I")["gold_status"] == "holdout_not_for_tuning"

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "expected" and item is not None:
                    raise AssertionError(f"Unreviewed gold value populated: {item}")
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for paper in papers:
        if paper["id"] != "CORR-HOLDOUT-I":
            walk(paper.get("assertions", {}))
