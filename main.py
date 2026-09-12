from __future__ import annotations
import argparse
from pathlib import Path
from synthex_v2.extractor import GeminiSensorExtractor
from synthex_v2.exporters import to_json_bytes, flatten_record

CATEGORIES = [
    'Metal Oxides', 'Metal Sulfides', 'Metal-Organic Frameworks',
    'Carbon-based', 'Polymeric Nanomaterials', 'Pure Metals / Alloys'
]


def main():
    parser = argparse.ArgumentParser(description='Synthex V2.1 — nanomaterial sensor literature extraction')
    parser.add_argument('pdf', nargs='?', default='data/my_paper.pdf')
    parser.add_argument('--category', choices=CATEGORIES, default=None)
    parser.add_argument('--mode', choices=['Full Sensor Record', 'Synthesis + Deposition', 'Sensor Performance'], default='Full Sensor Record')
    parser.add_argument('--format', choices=['json', 'csv'], default='json')
    parser.add_argument('--output', default=None)
    parser.add_argument('--model', default=None)
    args = parser.parse_args()

    path = Path(args.pdf)
    if not path.exists():
        raise SystemExit(f'PDF not found: {path}')
    extractor = GeminiSensorExtractor(model=args.model)
    record, warnings = extractor.extract_pdf(path, args.category, args.mode)

    out = Path(args.output or f'output/extracted_sensor_record.{args.format}')
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.format == 'json':
        out.write_bytes(to_json_bytes(record))
    else:
        flatten_record(record).to_csv(out, index=False)
    print(f'Saved: {out}')
    for warning in warnings:
        print(f'WARNING: {warning}')


if __name__ == '__main__':
    main()
