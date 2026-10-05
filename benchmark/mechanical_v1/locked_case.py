"""Read Mechanical paper benchmarks only when both source and reviewed gold match."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


CASE_DIR = Path(__file__).resolve().parent
LOCK_FILES = {
    "MECH-CREEP-B": "creep_b_source_lock.json",
    "MECH-FATIGUE-C": "fatigue_c_source_lock.json",
    "MECH-HARD-D": "hard_d_source_lock.json",
    "MECH-FRACTURE-E": "fracture_e_source_lock.json",
    "MECH-COMPUTE-F": "compute_f_source_lock.json",
    "MECH-REVIEW-G": "review_g_source_lock.json",
    "MECH-NEGATIVE-H": "negative_h_source_lock.json",
}


def load_locked_case(case_id: str):
    lock = json.loads((CASE_DIR / LOCK_FILES[case_id]).read_text(encoding="utf-8"))
    source = CASE_DIR / lock["source_file"]
    gold_path = CASE_DIR / lock["gold_file"]
    if sha256(source.read_bytes()).hexdigest() != lock["source_sha256"]:
        raise ValueError(f"{case_id} source PDF differs from its lock")
    if sha256(gold_path.read_bytes()).hexdigest() != lock["gold_sha256"]:
        raise ValueError(f"{case_id} reviewed gold differs from its lock")
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    if gold["case_id"] != case_id or gold["status"] != "locked_reviewed":
        raise ValueError(f"{case_id} gold is not independently reviewed")
    if gold["source"]["sha256"] != lock["source_sha256"]:
        raise ValueError(f"{case_id} gold source checksum differs from corpus lock")
    if case_id == "MECH-CREEP-B":
        count = sum(3 for _ in gold["rows"])
    elif case_id == "MECH-FATIGUE-C":
        count = sum(1 + (row["outcome"] == "failure") for row in gold["rows"])
    elif case_id in {"MECH-REVIEW-G", "MECH-NEGATIVE-H"}:
        count = len(gold["assertions"])
    else:
        count = len(gold["rows"])
    if count != lock["assertions"] or count != gold["assertion_count"]:
        raise ValueError(f"{case_id} gold assertion count differs from lock")
    return source, gold, lock
