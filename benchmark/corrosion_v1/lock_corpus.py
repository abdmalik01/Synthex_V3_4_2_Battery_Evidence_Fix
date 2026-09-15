from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "corpus_manifest.json"
LOCK_PATH = ROOT / "corpus_lock.json"
PDF_DIR = ROOT / "corpus pdfs"


def _normalize(text: str) -> str:
    text = text.casefold().replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def _doi_forms(doi: str) -> tuple[str, ...]:
    doi = doi.casefold().strip()
    return doi, f"https://doi.org/{doi}", f"doi:{doi}", f"doi: {doi}"


def _title_tokens(title: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", title.casefold())
        if len(token) >= 4
    }


def _read_pdf(path: Path) -> tuple[str, str]:
    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            chunks.append("")
    metadata = reader.metadata or {}
    metadata_text = " ".join(
        str(value) for value in (
            getattr(metadata, "title", None),
            metadata.get("/Title") if hasattr(metadata, "get") else None,
            metadata.get("/Subject") if hasattr(metadata, "get") else None,
            metadata.get("/Keywords") if hasattr(metadata, "get") else None,
        ) if value
    )
    return "\n".join(chunks), metadata_text


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _identity_match(entry: dict, raw_text: str, metadata_text: str = "") -> dict:
    text = _normalize(f"{metadata_text}\n{raw_text}")
    doi = entry["expected_doi"].casefold()
    doi_verified = any(_normalize(form) in text for form in _doi_forms(doi))

    expected_tokens = _title_tokens(entry["expected_title"])
    observed_tokens = {token for token in re.findall(r"[a-z0-9]+", text) if len(token) >= 4}
    coverage = len(expected_tokens & observed_tokens) / len(expected_tokens) if expected_tokens else 0.0
    title_verified = coverage >= 0.75
    return {
        "doi_verified": doi_verified,
        "title_token_coverage": round(coverage, 4),
        "title_verified": title_verified,
        "content_verified": bool(doi_verified and title_verified),
    }


def _load_pdf_cache() -> dict[str, dict]:
    cache: dict[str, dict] = {}
    for path in sorted(PDF_DIR.glob("*.pdf"), key=lambda item: item.name.casefold()):
        data = path.read_bytes()
        raw_text, metadata_text = _read_pdf(path)
        cache[path.name] = {
            "path": path,
            "data": data,
            "raw_text": raw_text,
            "metadata_text": metadata_text,
            "file_size_bytes": len(data),
            "git_blob_sha1": _git_blob_sha1(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return cache


def verify_entry(entry: dict, cache: dict[str, dict]) -> dict:
    if entry["filename"] not in cache:
        raise FileNotFoundError(f"Missing corpus PDF: {PDF_DIR / entry['filename']}")
    item = cache[entry["filename"]]

    if item["file_size_bytes"] != entry["file_size_bytes"]:
        raise ValueError(
            f"{entry['id']}: size mismatch: manifest={entry['file_size_bytes']} actual={item['file_size_bytes']}"
        )
    if item["git_blob_sha1"] != entry["git_blob_sha1"]:
        raise ValueError(
            f"{entry['id']}: Git blob mismatch: manifest={entry['git_blob_sha1']} actual={item['git_blob_sha1']}"
        )

    identity = _identity_match(entry, item["raw_text"], item["metadata_text"])
    return {
        "id": entry["id"],
        "role": entry["role"],
        "filename": entry["filename"],
        "expected_doi": entry["expected_doi"],
        "expected_title": entry["expected_title"],
        "file_size_bytes": item["file_size_bytes"],
        "git_blob_sha1": item["git_blob_sha1"],
        "sha256": item["sha256"],
        **identity,
    }


def _candidate_matches(entry: dict, cache: dict[str, dict]) -> list[dict]:
    candidates = []
    for filename, item in cache.items():
        identity = _identity_match(entry, item["raw_text"], item["metadata_text"])
        candidates.append({
            "filename": filename,
            **identity,
        })
    return sorted(
        candidates,
        key=lambda item: (
            item["content_verified"],
            item["doi_verified"],
            item["title_token_coverage"],
        ),
        reverse=True,
    )


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cache = _load_pdf_cache()
    results = [verify_entry(entry, cache) for entry in manifest["entries"]]
    discovery = {
        entry["id"]: _candidate_matches(entry, cache)[:3]
        for entry, result in zip(manifest["entries"], results)
        if not result["content_verified"]
    }
    listed = {entry["filename"] for entry in manifest["entries"]}
    unassigned = sorted(set(cache) - listed, key=str.casefold)

    payload = {
        "benchmark": manifest["benchmark"],
        "source_manifest": str(MANIFEST_PATH.relative_to(ROOT.parent.parent.parent)),
        "external_calls": 0,
        "files": results,
        "unassigned_pdfs": unassigned,
        "candidate_matches_for_unverified_entries": discovery,
        "all_content_verified": all(item["content_verified"] for item in results),
    }
    LOCK_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("=== CORROSION V1 CORPUS LOCK ===")
    print("External calls: 0")
    for item in results:
        status = "OK" if item["content_verified"] else "CHECK"
        print(
            f"{item['id']}: {status} | DOI={item['doi_verified']} | "
            f"title={item['title_verified']} ({item['title_token_coverage']:.0%}) | {item['filename']}"
        )
        if not item["content_verified"]:
            best = discovery.get(item["id"], [])
            if best:
                summary = "; ".join(
                    f"{candidate['filename']} [DOI={candidate['doi_verified']}, title={candidate['title_token_coverage']:.0%}]"
                    for candidate in best
                )
                print(f"  best local candidates: {summary}")
    if unassigned:
        print("Unassigned PDFs (never scored implicitly): " + ", ".join(unassigned))
    print(f"Wrote: {LOCK_PATH}")
    return 0 if payload["all_content_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
