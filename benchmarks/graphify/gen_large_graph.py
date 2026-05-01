"""Generate a synthetic 500-node graph fixture for benchmarks."""
from __future__ import annotations

import json
from pathlib import Path

NODE_COUNT = 500
EDGE_DENSITY = 3


def main() -> None:
    nodes = []
    for i in range(NODE_COUNT):
        nodes.append({
            "id": f"node-{i:04d}",
            "label": f"Component_{i}",
            "kind": "class" if i % 3 == 0 else "function" if i % 3 == 1 else "module",
            "file_path": f"src/pkg{i % 20}/mod{i % 50}.py",
        })

    links = []
    for i in range(NODE_COUNT):
        for j in range(1, EDGE_DENSITY + 1):
            target = (i + j * 7) % NODE_COUNT
            if target != i:
                links.append({
                    "source": f"node-{i:04d}",
                    "target": f"node-{target:04d}",
                    "relation": "calls" if j == 1 else "imports",
                })

    graph = {"nodes": nodes, "links": links}
    out_path = Path(__file__).parent / "large_graph.json"
    out_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    print(f"Wrote {len(nodes)} nodes, {len(links)} edges to {out_path}")


if __name__ == "__main__":
    main()
