#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"

if SRC_DIR.is_dir():
    sys.path.insert(0, str(SRC_DIR))

LARGE_FIXTURE_GRAPH = REPO_ROOT / "benchmarks" / "graphify" / "large_graph.json"
LEGACY_FIXTURE_GRAPH = (
    REPO_ROOT
    / "benchmarks"
    / "fixtures"
    / "integration"
    / "pinned_011_graph_present"
    / "graph.json"
)

SAMPLE_CONCEPTS = [
    "AuthMiddleware",
    "TokenValidator",
    "database pool",
    "rate limiting",
    "cache layer",
    "event bus",
    "migration runner",
    "health check",
    "query builder",
    "logging",
]


def _percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def bench_parse(graph_path: Path, iterations: int = 100) -> dict[str, Any]:
    from ahadiff.graphify import parse_graph_json

    graph = parse_graph_json(graph_path)
    times: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        graph = parse_graph_json(graph_path)
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)

    return {
        "operation": "parse_graph_json",
        "iterations": iterations,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.links),
        "mean_ms": round(statistics.mean(times), 3),
        "median_ms": round(statistics.median(times), 3),
        "p95_ms": round(_percentile(times, 0.95), 3),
        "p99_ms": round(_percentile(times, 0.99), 3),
    }


def bench_match(graph_path: Path, iterations: int = 50) -> dict[str, Any]:
    from ahadiff.graphify import match_concepts, parse_graph_json

    graph = parse_graph_json(graph_path)
    labels = [n.label for n in graph.nodes if n.label]
    times: list[float] = []
    total_matches = 0

    for _ in range(iterations):
        matches_this_round = 0
        start = time.perf_counter()
        for concept in SAMPLE_CONCEPTS:
            hits = match_concepts(concept, labels, threshold=0.3, max_results=5)
            matches_this_round += len(hits)
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)
        total_matches = matches_this_round

    return {
        "operation": "match_concepts (10 queries)",
        "iterations": iterations,
        "matches_per_round": total_matches,
        "mean_ms": round(statistics.mean(times), 3),
        "median_ms": round(statistics.median(times), 3),
        "p95_ms": round(_percentile(times, 0.95), 3),
    }


def bench_link(graph_path: Path, iterations: int = 50) -> dict[str, Any]:
    from ahadiff.graphify import link_concepts, parse_graph_json

    graph = parse_graph_json(graph_path)
    times: list[float] = []
    link_count = 0

    for _ in range(iterations):
        start = time.perf_counter()
        links = link_concepts(graph, SAMPLE_CONCEPTS)
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)
        link_count = len(links)

    return {
        "operation": "link_concepts (10 concepts)",
        "iterations": iterations,
        "links_found": link_count,
        "mean_ms": round(statistics.mean(times), 3),
        "median_ms": round(statistics.median(times), 3),
        "p95_ms": round(_percentile(times, 0.95), 3),
    }


def bench_search(graph_path: Path, iterations: int = 50) -> dict[str, Any]:
    from ahadiff.graphify import parse_graph_json, search_graph_nodes

    graph = parse_graph_json(graph_path)
    queries = ["auth", "database", "cache", "event", "config"]
    times: list[float] = []
    total_hits = 0

    for _ in range(iterations):
        hits_this_round = 0
        start = time.perf_counter()
        for q in queries:
            results = search_graph_nodes(graph, q, limit=10, threshold=0.2)
            hits_this_round += len(results)
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)
        total_hits = hits_this_round

    return {
        "operation": "search_graph_nodes (5 queries)",
        "iterations": iterations,
        "hits_per_round": total_hits,
        "mean_ms": round(statistics.mean(times), 3),
        "median_ms": round(statistics.median(times), 3),
        "p95_ms": round(_percentile(times, 0.95), 3),
    }


def bench_slice(graph_path: Path, iterations: int = 50) -> dict[str, Any]:
    from ahadiff.graphify import parse_graph_json, slice_by_files

    graph = parse_graph_json(graph_path)
    file_set = {"src/auth/middleware.py", "src/db/pool.py"}
    times: list[float] = []
    node_count = 0

    for _ in range(iterations):
        start = time.perf_counter()
        sub = slice_by_files(graph, file_set, hop_depth=2)
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)
        node_count = len(sub.node_ids)

    return {
        "operation": "slice_by_files (2 files, 2 hops)",
        "iterations": iterations,
        "subgraph_nodes": node_count,
        "mean_ms": round(statistics.mean(times), 3),
        "median_ms": round(statistics.median(times), 3),
        "p95_ms": round(_percentile(times, 0.95), 3),
    }


def main() -> None:
    fixture_graph = LARGE_FIXTURE_GRAPH if LARGE_FIXTURE_GRAPH.is_file() else LEGACY_FIXTURE_GRAPH
    if not fixture_graph.is_file():
        print(f"ERROR: fixture not found: {fixture_graph}", file=sys.stderr)
        sys.exit(1)

    results: list[dict[str, Any]] = []
    for bench_fn in (bench_parse, bench_match, bench_link, bench_search, bench_slice):
        result = bench_fn(fixture_graph)
        results.append(result)
        print(
            f"  {result['operation']}: mean={result['mean_ms']}ms median={result['median_ms']}ms",
            file=sys.stderr,
        )

    payload = {
        "benchmarks": results,
        "fixture": str(fixture_graph.name),
        "status": "ok",
    }
    json.dump(payload, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
