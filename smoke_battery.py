from __future__ import annotations
import json
import sys
from pathlib import Path
from synthex_platform.extraction import BatteryGeminiExtractor, assemble_battery_archive

if len(sys.argv) < 2:
    raise SystemExit('Usage: python smoke_battery.py "path/to/battery_paper.pdf" [output.json]')
extractor = BatteryGeminiExtractor()
doc = extractor.extract_pdf(sys.argv[1])
archive = assemble_battery_archive(doc, model=extractor.model)
payload = json.dumps(archive.model_dump(exclude_none=True), ensure_ascii=False, indent=2)
print(payload)
if len(sys.argv) >= 3:
    Path(sys.argv[2]).write_text(payload, encoding="utf-8")
    print(f"\nSaved: {sys.argv[2]}")
