"""Generate synthetic graph fixtures for benchmarks.

Produces three fixtures:
  - large_graph.json      (500 nodes, ~1500 edges)
  - xlarge_graph.json     (5000 nodes, ~15000 edges)
  - ultra_graph.json      (10000 nodes, ~30000 edges)
"""

from __future__ import annotations

import json
from pathlib import Path


def _generate_graph(node_count: int, edge_density: int) -> dict[str, object]:
    nodes: list[dict[str, str]] = []
    for i in range(node_count):
        nodes.append(
            {
                "id": f"node-{i:05d}",
                "label": f"Component_{i}",
                "kind": "class" if i % 3 == 0 else "function" if i % 3 == 1 else "module",
                "file_path": f"src/pkg{i % 20}/mod{i % 50}.py",
            }
        )

    links: list[dict[str, str]] = []
    for i in range(node_count):
        for j in range(1, edge_density + 1):
            target = (i + j * 7) % node_count
            if target != i:
                links.append(
                    {
                        "source": f"node-{i:05d}",
                        "target": f"node-{target:05d}",
                        "relation": "calls" if j == 1 else "imports",
                    }
                )

    return {"nodes": nodes, "links": links}


def _write_fixture(name: str, node_count: int, edge_density: int) -> None:
    graph = _generate_graph(node_count, edge_density)
    out_path = Path(__file__).parent / name
    out_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    print(
        f"Wrote {len(graph['nodes'])} nodes, "  # type: ignore[arg-type]
        f"{len(graph['links'])} edges to {out_path}"  # type: ignore[arg-type]
    )


def main() -> None:
    _write_fixture("large_graph.json", node_count=500, edge_density=3)
    _write_fixture("xlarge_graph.json", node_count=5000, edge_density=3)
    _write_fixture("ultra_graph.json", node_count=10000, edge_density=3)


if __name__ == "__main__":
    main()
