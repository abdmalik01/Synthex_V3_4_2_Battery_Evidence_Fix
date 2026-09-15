from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "corpus_manifest.json"
LOCK_PATH = ROOT / "corpus_lock.json"


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


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            chunks.append("")
    return "\n".join(chunks)


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def verify_entry(entry: dict) -> dict:
    path = ROOT / "corpus pdfs" / entry["filename"]
    if not path.exists():
        raise FileNotFoundError(f"Missing corpus PDF: {path}")

    data = path.read_bytes()
    size = len(data)
    git_blob_sha1 = _git_blob_sha1(data)
    sha256 = hashlib.sha256(data).hexdigest()

    if size != entry["file_size_bytes"]:
        raise ValueError(
            f"{entry['id']}: size mismatch: manifest={entry['file_size_bytes']} actual={size}"
        )
    if git_blob_sha1 != entry["git_blob_sha1"]:
        raise ValueError(
            f"{entry['id']}: Git blob mismatch: manifest={entry['git_blob_sha1']} actual={git_blob_sha1}"
        )

    raw_text = _pdf_text(path)
    text = _normalize(raw_text)
    doi = entry["expected_doi"].casefold()
    doi_verified = any(_normalize(form) in text for form in _doi_forms(doi))

    expected_tokens = _title_tokens(entry["expected_title"])
    observed_tokens = {token for token in re.findall(r"[a-z0-9]+", text) if len(token) >= 4}
    title_token_coverage = (
        len(expected_tokens & observed_tokens) / len(expected_tokens)
        if expected_tokens else 0.0
    )
    title_verified = title_token_coverage >= 0.75

    return {
        "id": entry["id"],
        "role": entry["role"],
        "filename": entry["filename"],
        "expected_doi": entry["expected_doi"],
        "expected_title": entry["expected_title"],
        "file_size_bytes": size,
        "git_blob_sha1": git_blob_sha1,
        "sha256": sha256,
        "doi_verified": doi_verified,
        "title_token_coverage": round(title_token_coverage, 4),
        "title_verified": title_verified,
        "content_verified": bool(doi_verified and title_verified),
    }


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    results = [verify_entry(entry) for entry in manifest["entries"]]
    payload = {
        "benchmark": manifest["benchmark"],
        "source_manifest": str(MANIFEST_PATH.relative_to(ROOT.parent.parent.parent)),
        "external_calls": 0,
        "files": results,
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
    print(f"Wrote: {LOCK_PATH}")
    return 0 if payload["all_content_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
