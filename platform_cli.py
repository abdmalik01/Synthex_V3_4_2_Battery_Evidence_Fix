from __future__ import annotations

import argparse
import json
from pathlib import Path

from synthex_platform.benchmarks import all_benchmarks
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.graph import export_graph
from synthex_platform.storage import JsonlArchiveStore


def main():
    parser = argparse.ArgumentParser(description="Synthex V3 platform utilities")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("domains")
    sub.add_parser("benchmarks")
    graph = sub.add_parser("build-graph")
    graph.add_argument("--archive", default="data/archive/archives.jsonl")
    graph.add_argument("--out", default="data/graph")
    args = parser.parse_args()
    registry = DomainRegistry()
    if args.command == "domains":
        print(json.dumps([{k: d[k] for k in ("slug", "name", "version", "description")} for d in registry.list_domains()], indent=2))
    elif args.command == "benchmarks":
        print(json.dumps(all_benchmarks(registry), indent=2))
    elif args.command == "build-graph":
        store = JsonlArchiveStore(args.archive)
        nodes, edges = export_graph(store.iter_archives() or [], args.out)
        print(f"Wrote {nodes} and {edges}")


if __name__ == "__main__":
    main()
