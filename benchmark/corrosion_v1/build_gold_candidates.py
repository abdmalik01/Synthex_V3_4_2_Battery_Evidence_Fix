from __future__ import annotations

import json
import re
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "corpus_manifest.json"
OUTPUT_PATH = ROOT / "gold_candidates.json"
PDF_DIR = ROOT / "corpus pdfs"

ROLE_TERMS = {
    "bare_alloy_polarization": [
        "corrosion potential", "ecorr", "corrosion current density", "icorr",
        "pitting potential", "reference electrode", "scan rate", "nacl",
    ],
    "coating_surface_treatment": [
        "corrosion current density", "icorr", "charge transfer resistance", "rct",
        "protection efficiency", "coating", "surface treatment", "equivalent circuit",
    ],
    "corrosion_inhibitor": [
        "inhibition efficiency", "corrosion current density", "icorr", "inhibitor",
        "concentration", "weight loss", "charge transfer resistance", "rct",
    ],
    "eis_heavy": [
        "electrochemical impedance", "eis", "charge transfer resistance", "rct",
        "solution resistance", "rs", "constant phase element", "cpe",
        "equivalent circuit", "frequency", "amplitude",
    ],
    "immersion_weight_loss": [
        "weight loss", "mass loss", "corrosion rate", "inhibition efficiency",
        "immersion", "exposure time", "temperature", "hydrochloric acid",
    ],
    "computational_corrosion": [
        "density functional theory", "dft", "adsorption energy", "interaction energy",
        "homo", "lumo", "fe(110)", "molecular dynamics",
    ],
    "review_contamination_control": [
        "review", "electrochemical impedance", "potentiodynamic", "open circuit potential",
        "salt spray", "corrosion protection",
    ],
    "non_corrosion_negative_control": [
        "lithium ion", "lifepo4", "cathode", "electrochemical impedance", "nyquist",
        "battery", "capacity",
    ],
}

MAX_HITS_PER_TERM = 4
CONTEXT_CHARS = 320


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


def _page_texts(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(_normalize(page.extract_text() or ""))
        except Exception:
            pages.append("")
    return pages


def _snippet(text: str, start: int, end: int) -> str:
    left = max(0, start - CONTEXT_CHARS)
    right = min(len(text), end + CONTEXT_CHARS)
    snippet = text[left:right].strip()
    return snippet


def _find_hits(pages: list[str], terms: list[str]) -> list[dict]:
    hits: list[dict] = []
    for term in terms:
        found_for_term = 0
        pattern = re.compile(re.escape(term), flags=re.IGNORECASE)
        for page_no, text in enumerate(pages, start=1):
            if not text:
                continue
            for match in pattern.finditer(text):
                hits.append({
                    "term": term,
                    "page": page_no,
                    "snippet": _snippet(text, match.start(), match.end()),
                })
                found_for_term += 1
                if found_for_term >= MAX_HITS_PER_TERM:
                    break
            if found_for_term >= MAX_HITS_PER_TERM:
                break
    return hits


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    papers: list[dict] = []

    for entry in manifest["entries"]:
        if entry["id"] == "CORR-HOLDOUT-I":
            papers.append({
                "id": entry["id"],
                "filename": entry["filename"],
                "role": entry["role"],
                "status": "holdout_not_mined",
                "hits": [],
            })
            continue

        path = PDF_DIR / entry["filename"]
        if not path.exists():
            raise FileNotFoundError(path)
        pages = _page_texts(path)
        terms = ROLE_TERMS.get(entry["role"], [])
        hits = _find_hits(pages, terms)
        papers.append({
            "id": entry["id"],
            "filename": entry["filename"],
            "role": entry["role"],
            "doi": entry["expected_doi"],
            "title": entry["expected_title"],
            "page_count": len(pages),
            "status": "candidate_text_only_not_gold",
            "candidate_terms": terms,
            "hits": hits,
        })

    payload = {
        "benchmark": manifest["benchmark"],
        "external_calls": 0,
        "policy": {
            "candidate_snippets_are_not_gold": True,
            "manual_source_review_required": True,
            "no_llm_generated_gold": True,
            "holdout_not_mined": True,
            "no_unit_or_reference_electrode_conversion": True,
        },
        "papers": papers,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("=== CORROSION V1 GOLD CANDIDATE HARVEST ===")
    print("External calls: 0")
    for paper in papers:
        if paper["status"] == "holdout_not_mined":
            print(f"{paper['id']}: HOLDOUT | not mined | {paper['filename']}")
        else:
            print(f"{paper['id']}: {len(paper['hits'])} candidate snippets | {paper['page_count']} pages | {paper['filename']}")
    print(f"Wrote: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
