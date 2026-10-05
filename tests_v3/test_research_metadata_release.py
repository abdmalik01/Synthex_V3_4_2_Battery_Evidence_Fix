"""The public research branch publishes source identities, not source bytes."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmark" / "omitted_binary_manifest.json"


def test_omitted_binary_manifest_is_complete_and_paths_are_safe():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    files = data["files"]
    assert len(files) == 55
    paths = [item["path"] for item in files]
    assert paths == sorted(set(paths))
    for item in files:
        path = Path(item["path"])
        assert not path.is_absolute()
        assert ".." not in path.parts
        assert item["path"].startswith("benchmark/")
        assert path.suffix in {".pdf", ".xlsx", ".zip"}
        assert item["bytes"] > 0
        assert re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        assert not (ROOT / path).exists()


def test_thermoelectric_supplement_is_link_and_hash_only():
    lock = json.loads((ROOT / "benchmark/thermoelectrics_v1/source_lock.json").read_text(encoding="utf-8"))
    assert lock["supplementary_file_sha256"] == "7f3f950c6e2385622056cfd49481edca38cd0e40234f2dc3ef84dc112a9d05de"
    assert not (ROOT / "benchmark/thermoelectrics_v1" / lock["supplementary_file"]).exists()
