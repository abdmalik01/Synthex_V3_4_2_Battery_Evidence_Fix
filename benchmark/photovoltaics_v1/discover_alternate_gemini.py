"""Discover exact alternate Gemini model IDs exposed to the configured account."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from google import genai

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synthex_platform.providers import discover_gemini_models, is_general_text_gemini_model


EXCLUDED = "gemini-3.5-flash"


def _bare(model_id: str) -> str:
    return model_id.removeprefix("models/")


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("A configured Gemini credential is required for model discovery.")
    discovered = list(discover_gemini_models(genai.Client(api_key=api_key)))
    eligible = [
        item for item in discovered
        if is_general_text_gemini_model(item) and _bare(item["model_id"]) != EXCLUDED
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "output/photovoltaics_v1/provider_runs/model_discovery" / f"{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider_name": "gemini",
        "discovery_method": "configured_account_models_list",
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "excluded_model_ids": [EXCLUDED],
        "models": discovered,
        "eligible_alternate_models": eligible,
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "artifact": str(output),
        "eligible_alternate_model_ids": [item["model_id"] for item in eligible],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
