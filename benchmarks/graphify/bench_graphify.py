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
XLARGE_GRAPH_PATH = Path(__file__).parent / "xlarge_graph.json"

# Perf gate thresholds (avg milliseconds)
_GATE_PARSE_500 = 500.0
_GATE_PARSE_5000 = 5000.0
_GATE_FTS_BUILD = 2000.0
_GATE_FTS_SEARCH = 100.0


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


def bench_parse(graph_path: Path, label_suffix: str) -> dict[str, object]:
    from ahadiff.graphify import parse_graph_json_text

    raw = graph_path.read_text(encoding="utf-8")

    def do_parse() -> None:
        parse_graph_json_text(raw)

    return _bench(f"Parse graph.json ({label_suffix})", do_parse)


def bench_fts_index_build(graph_path: Path, label_suffix: str) -> dict[str, object]:
    from ahadiff.review.database import import_graph_nodes, initialize_review_db

    raw = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = raw["nodes"]

    def do_build() -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "review.sqlite"
            initialize_review_db(db)
            import_graph_nodes(db, nodes)

    return _bench(f"FTS index build ({label_suffix})", do_build, repeat=3)


def bench_search_fts(graph_path: Path, label_suffix: str) -> dict[str, object]:
    from ahadiff.review.database import import_graph_nodes, initialize_review_db
    from ahadiff.review.search import search_graph_nodes_fts

    raw = json.loads(graph_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "review.sqlite"
        initialize_review_db(db)
        import_graph_nodes(db, raw["nodes"])

        def do_fts_search() -> None:
            search_graph_nodes_fts(db, "Component", limit=20)

        return _bench(f"FTS search ({label_suffix})", do_fts_search, repeat=20)


def bench_search_inmemory(graph_path: Path, label_suffix: str) -> dict[str, object]:
    from ahadiff.graphify import parse_graph_json_text
    from ahadiff.graphify.search import search_graph_nodes

    raw = graph_path.read_text(encoding="utf-8")
    graph = parse_graph_json_text(raw)

    def do_inmemory_search() -> None:
        search_graph_nodes(graph, "Component", limit=20)

    return _bench(f"In-memory search ({label_suffix})", do_inmemory_search, repeat=20)


def bench_concept_linking(graph_path: Path, label_suffix: str) -> dict[str, object]:
    from ahadiff.graphify import parse_graph_json_text
    from ahadiff.graphify.linker import link_concepts

    raw = graph_path.read_text(encoding="utf-8")
    graph = parse_graph_json_text(raw)
    concepts = [f"Component_{i}" for i in range(50)]

    def do_link() -> None:
        link_concepts(graph, concepts, threshold=0.5)

    return _bench(f"Concept linking (50 concepts x {label_suffix})", do_link, repeat=3)


def _run_fixture(graph_path: Path, label_suffix: str) -> list[dict[str, object]]:
    """Run all benchmarks for a single fixture, return result dicts."""
    return [
        bench_parse(graph_path, label_suffix),
        bench_fts_index_build(graph_path, label_suffix),
        bench_search_fts(graph_path, label_suffix),
        bench_search_inmemory(graph_path, label_suffix),
        bench_concept_linking(graph_path, label_suffix),
    ]


def _apply_perf_gates(results: list[dict[str, object]]) -> list[str]:
    """Check perf gate thresholds. Return list of failure messages."""
    failures: list[str] = []
    for r in results:
        op = str(r["operation"])
        avg = float(r["avg_ms"])  # type: ignore[arg-type]

        if "Parse" in op and "500 nodes" in op and avg > _GATE_PARSE_500:
            failures.append(f"PERF GATE FAIL: {op} avg={avg:.1f}ms > {_GATE_PARSE_500}ms")
        elif "Parse" in op and "5000 nodes" in op and avg > _GATE_PARSE_5000:
            failures.append(f"PERF GATE FAIL: {op} avg={avg:.1f}ms > {_GATE_PARSE_5000}ms")
        elif "FTS index build" in op and avg > _GATE_FTS_BUILD:
            failures.append(f"PERF GATE FAIL: {op} avg={avg:.1f}ms > {_GATE_FTS_BUILD}ms")
        elif "FTS search" in op and avg > _GATE_FTS_SEARCH:
            failures.append(f"PERF GATE FAIL: {op} avg={avg:.1f}ms > {_GATE_FTS_SEARCH}ms")

    return failures


def main() -> None:
    if not LARGE_GRAPH_PATH.exists():
        print(f"Missing fixture: {LARGE_GRAPH_PATH}", file=sys.stderr)
        print("Run: python benchmarks/graphify/gen_large_graph.py", file=sys.stderr)
        sys.exit(1)

    all_results: list[dict[str, object]] = []
    fixtures_used: list[str] = []

    # 500-node fixture (required)
    print("--- 500-node fixture ---", file=sys.stderr)
    all_results.extend(_run_fixture(LARGE_GRAPH_PATH, "500 nodes"))
    fixtures_used.append(str(LARGE_GRAPH_PATH.name))

    # 5000-node fixture (optional)
    if XLARGE_GRAPH_PATH.exists():
        print("--- 5000-node fixture ---", file=sys.stderr)
        all_results.extend(_run_fixture(XLARGE_GRAPH_PATH, "5000 nodes"))
        fixtures_used.append(str(XLARGE_GRAPH_PATH.name))
    else:
        print(
            f"WARNING: 5000-node fixture not found at {XLARGE_GRAPH_PATH}, skipping",
            file=sys.stderr,
        )

    # Perf gate assertions
    failures = _apply_perf_gates(all_results)
    gate_status = "fail" if failures else "ok"
    for msg in failures:
        print(msg, file=sys.stderr)

    payload = {
        "benchmarks": all_results,
        "fixtures": fixtures_used,
        "gate_status": gate_status,
        "gate_failures": failures,
        "status": "ok",
    }
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
