from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable
from synthex_platform.core.archive import SynthexArchive


def archive_to_graph(archive: SynthexArchive) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    edges: list[dict] = []

    nodes.append({"id": archive.metadata.archive_id, "type": "archive", "domain": archive.metadata.domain})
    for s in archive.sources:
        nodes.append({"id": s.source_id, "type": "source", "title": s.title, "doi": s.doi, "year": s.year})
    for m in archive.materials:
        nodes.append({"id": m.material_id, "type": "material", "name": m.name, "formula": m.formula, "elements": m.elements, "phase": m.phase, "tags": m.tags})
    for d in archive.devices:
        nodes.append({"id": d.device_id, "type": "device", "name": d.name, "device_type": d.device_type, "material_ids": d.material_ids, "configuration": d.configuration, "tags": d.tags})
    for p in archive.processes:
        nodes.append({"id": p.process_id, "type": "process", "name": p.name, "family": p.family})
    for e in archive.experiments:
        nodes.append({"id": e.experiment_id, "type": "experiment", "experiment_type": e.experiment_type, "target": e.target})
        for measurement in e.outputs:
            prop_id = f"{e.experiment_id}:prop:{measurement.property}:{len(nodes)}"
            nodes.append({"id": prop_id, "type": "property", **measurement.model_dump(exclude_none=True)})
            edges.append({"source": e.experiment_id, "predicate": "has_property", "target": prop_id})
    for c in archive.calculations:
        nodes.append({"id": c.calculation_id, "type": "calculation", "calculation_type": c.calculation_type, "code": c.code, "method": c.method, "functional": c.functional})
        for measurement in c.outputs:
            prop_id = f"{c.calculation_id}:prop:{measurement.property}:{len(nodes)}"
            nodes.append({"id": prop_id, "type": "property", **measurement.model_dump(exclude_none=True)})
            edges.append({"source": c.calculation_id, "predicate": "has_property", "target": prop_id})
    edges.extend({"id": r.relation_id, "source": r.subject_id, "predicate": r.predicate, "target": r.object_id, "attributes": r.attributes} for r in archive.relationships)
    return nodes, edges


def export_graph(archives: Iterable[SynthexArchive], directory: str | Path) -> tuple[Path, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    node_path = directory / "nodes.jsonl"
    edge_path = directory / "edges.jsonl"
    seen_nodes = set()
    seen_edges = set()
    with node_path.open("w", encoding="utf-8") as nf, edge_path.open("w", encoding="utf-8") as ef:
        for archive in archives:
            nodes, edges = archive_to_graph(archive)
            for node in nodes:
                if node["id"] not in seen_nodes:
                    nf.write(json.dumps(node, ensure_ascii=False) + "\n")
                    seen_nodes.add(node["id"])
            for edge in edges:
                edge_key = edge.get("id") or (edge["source"], edge["predicate"], edge["target"])
                if str(edge_key) not in seen_edges:
                    ef.write(json.dumps(edge, ensure_ascii=False) + "\n")
                    seen_edges.add(str(edge_key))
    return node_path, edge_path
