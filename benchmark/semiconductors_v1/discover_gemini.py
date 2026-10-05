"""Persist exact Gemini model discovery for controlled Semiconductor benchmarks."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from synthex_platform.providers import discover_gemini_models, is_general_text_gemini_model


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output/semiconductors_v1/provider_runs/model_discovery"


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("A configured Gemini credential is required for model discovery.")
    discovered = list(discover_gemini_models(genai.Client(api_key=api_key)))
    eligible = [item for item in discovered if is_general_text_gemini_model(item)]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / f"{stamp}.json"
    payload = {
        "provider_name": "gemini",
        "discovery_method": "configured_account_models_list",
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "models": discovered,
        "eligible_general_text_models": eligible,
    }
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({"artifact": str(path), "eligible_general_text_models": eligible}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
