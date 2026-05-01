"""Benchmark Graphify operations: parse, FTS index build, search, concept linking."""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

LARGE_GRAPH_PATH = Path(__file__).parent / "large_graph.json"


def _bench(label: str, fn, *, repeat: int = 5) -> dict[str, object]:  # noqa: ANN001
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    avg = sum(times) / len(times)
    lo, hi = min(times) * 1000, max(times) * 1000
    print(
        f"  {label}: avg={avg*1000:.2f}ms  min={lo:.2f}ms  max={hi:.2f}ms",
        file=sys.stderr,
    )
    return {
        "operation": label,
        "repeat": repeat,
        "avg_ms": round(avg * 1000, 3),
        "min_ms": round(lo, 3),
        "max_ms": round(hi, 3),
    }


def bench_parse() -> dict[str, object]:
    from ahadiff.graphify import parse_graph_json_text

    raw = LARGE_GRAPH_PATH.read_text(encoding="utf-8")

    def do_parse() -> None:
        parse_graph_json_text(raw)

    return _bench("Parse graph.json (500 nodes)", do_parse)


def bench_fts_index_build() -> dict[str, object]:
    from ahadiff.review.database import import_graph_nodes, initialize_review_db

    raw = json.loads(LARGE_GRAPH_PATH.read_text(encoding="utf-8"))
    nodes = raw["nodes"]

    def do_build() -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "review.sqlite"
            initialize_review_db(db)
            import_graph_nodes(db, nodes)

    return _bench("FTS index build (500 nodes)", do_build, repeat=3)


def bench_search_fts() -> dict[str, object]:
    from ahadiff.review.database import import_graph_nodes, initialize_review_db
    from ahadiff.review.search import search_graph_nodes_fts

    raw = json.loads(LARGE_GRAPH_PATH.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "review.sqlite"
        initialize_review_db(db)
        import_graph_nodes(db, raw["nodes"])

        def do_fts_search() -> None:
            search_graph_nodes_fts(db, "Component", limit=20)

        return _bench("FTS search (500 nodes)", do_fts_search, repeat=20)


def bench_search_inmemory() -> dict[str, object]:
    from ahadiff.graphify import parse_graph_json_text
    from ahadiff.graphify.search import search_graph_nodes

    raw = LARGE_GRAPH_PATH.read_text(encoding="utf-8")
    graph = parse_graph_json_text(raw)

    def do_inmemory_search() -> None:
        search_graph_nodes(graph, "Component", limit=20)

    return _bench("In-memory search (500 nodes)", do_inmemory_search, repeat=20)


def bench_concept_linking() -> dict[str, object]:
    from ahadiff.graphify import parse_graph_json_text
    from ahadiff.graphify.linker import link_concepts

    raw = LARGE_GRAPH_PATH.read_text(encoding="utf-8")
    graph = parse_graph_json_text(raw)
    concepts = [f"Component_{i}" for i in range(50)]

    def do_link() -> None:
        link_concepts(graph, concepts, threshold=0.5)

    return _bench("Concept linking (50 concepts x 500 nodes)", do_link, repeat=3)


def main() -> None:
    if not LARGE_GRAPH_PATH.exists():
        print(f"Missing fixture: {LARGE_GRAPH_PATH}", file=sys.stderr)
        print("Run: python benchmarks/graphify/gen_large_graph.py", file=sys.stderr)
        sys.exit(1)

    results = [
        bench_parse(),
        bench_fts_index_build(),
        bench_search_fts(),
        bench_search_inmemory(),
        bench_concept_linking(),
    ]
    payload = {"benchmarks": results, "fixture": str(LARGE_GRAPH_PATH.name), "status": "ok"}
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
