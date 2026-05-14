#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

from ahadiff.review.database import initialize_review_db
from ahadiff.serve import ServeState, create_app

SAMPLES_PER_ROUTE = 30
WARMUP_PER_ROUTE = 5
TARGET_P95_MS = 50.0
FAIL_P95_MS = 500.0
TOKEN = "bench-token"
ROUTES = (
    ("GET /api/runs", "/api/runs?page_size=100", False),
    ("GET /api/concepts", "/api/concepts?limit=200", False),
    ("GET /api/graph/concepts", "/api/graph/concepts?limit=1000", False),
    ("GET /api/search", "/api/search?q=Concept&limit=100", True),
    ("GET /api/ratchet/transparency", "/api/ratchet/transparency", True),
)


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _write_large_fixture(state_dir: Path) -> None:
    state_dir.mkdir(parents=True)
    initialize_review_db(state_dir / "review.sqlite")
    concepts_path = state_dir / "concepts.jsonl"
    with concepts_path.open("w", encoding="utf-8") as handle:
        for index in range(2_000):
            handle.write(
                json.dumps(
                    {
                        "term_key": f"concept-{index:04d}",
                        "display_name": f"Concept {index:04d}",
                        "concept": f"Concept {index:04d}",
                        "related_claims": [f"claim-{index:04d}"],
                        "file_refs": [f"src/module_{index % 40}.py"],
                        "source_refs": [f"run_{index:032x}"],
                        "updated_by_runs": [f"run_{index:032x}"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    nodes = [
        {
            "id": f"node-{index:04d}",
            "label": f"Concept {index:04d}",
            "file_path": f"src/module_{index % 40}.py",
        }
        for index in range(1_000)
    ]
    links = [
        {
            "source": f"node-{index:04d}",
            "target": f"node-{index + 1:04d}",
            "kind": "calls",
        }
        for index in range(999)
    ]
    graph_text = json.dumps({"nodes": nodes, "links": links}, ensure_ascii=False)
    graph_sha256 = sha256(graph_text.encode("utf-8")).hexdigest()
    source_graph_dir = state_dir.parent / "graphify-out"
    source_graph_dir.mkdir()
    (source_graph_dir / "graph.json").write_text(graph_text, encoding="utf-8")
    graph_dir = state_dir / "graphify"
    graph_dir.mkdir()
    (graph_dir / "graph.json").write_text(graph_text, encoding="utf-8")
    (graph_dir / "provenance.json").write_text(
        json.dumps(
            {
                "edge_count": str(len(links)),
                "graph_sha256": graph_sha256,
                "import_time": datetime.now(UTC).isoformat(),
                "node_count": str(len(nodes)),
                "parser_version": "bench",
                "source_path": "graphify-out/graph.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _request(client: TestClient, path: str, requires_token: bool) -> tuple[int, float, bytes]:
    headers = {"X-AhaDiff-Token": TOKEN} if requires_token else {}
    started = time.perf_counter()
    response = client.get(path, headers=headers)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return response.status_code, elapsed_ms, response.content


def _validation_error(name: str, body: bytes) -> str | None:
    if name == "GET /api/concepts":
        payload = json.loads(body.decode("utf-8"))
        content = payload.get("content")
        if not isinstance(content, str) or len(content.splitlines()) < 200:
            return "concepts_response_too_small"
    if name == "GET /api/graph/concepts":
        payload = json.loads(body.decode("utf-8"))
        nodes = payload.get("nodes")
        if not isinstance(nodes, list) or len(nodes) < 1_000:
            return "graph_nodes_response_too_small"
    return None


def _measure_route(
    client: TestClient,
    name: str,
    path: str,
    requires_token: bool,
) -> dict[str, Any]:
    for _ in range(WARMUP_PER_ROUTE):
        _request(client, path, requires_token)
    samples: list[float] = []
    response_bytes: list[int] = []
    status_counts: dict[str, int] = {}
    validation_errors: list[str] = []
    for _ in range(SAMPLES_PER_ROUTE):
        status, elapsed_ms, body = _request(client, path, requires_token)
        samples.append(elapsed_ms)
        response_bytes.append(len(body))
        key = str(status)
        status_counts[key] = status_counts.get(key, 0) + 1
        if status < 200 or status >= 300:
            validation_errors.append(f"http_status_{status}")
            continue
        try:
            error = _validation_error(name, body)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
            validation_errors.append(f"invalid_response:{type(exc).__name__}")
        else:
            if error is not None:
                validation_errors.append(error)
    p95 = round(_percentile(samples, 0.95), 3)
    status = "pass" if p95 <= FAIL_P95_MS else "fail"
    if TARGET_P95_MS < p95 <= FAIL_P95_MS:
        status = "warn"
    if validation_errors:
        status = "fail"
    return {
        "http_status_counts": status_counts,
        "metrics": {
            "mean_ms": round(statistics.fmean(samples), 3),
            "p50_ms": round(_percentile(samples, 0.50), 3),
            "p95_ms": p95,
            "p99_ms": round(_percentile(samples, 0.99), 3),
        },
        "response_bytes": {
            "min": min(response_bytes),
            "mean": round(statistics.fmean(response_bytes), 1),
            "max": max(response_bytes),
        },
        "samples": SAMPLES_PER_ROUTE,
        "status": status,
        "target_p95_ms": TARGET_P95_MS,
        "fail_p95_ms": FAIL_P95_MS,
        "validation_errors": sorted(set(validation_errors)),
    }


def run_gate() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ahadiff-serve-bench-") as tmp:
        state_dir = Path(tmp).resolve() / ".ahadiff"
        _write_large_fixture(state_dir)
        client = TestClient(
            create_app(ServeState(state_dir=state_dir, token=TOKEN, locale="en")),
            base_url="http://localhost:8765",
        )
        results = {
            name: _measure_route(client, name, path, requires_token)
            for name, path, requires_token in ROUTES
        }
    statuses = {item["status"] for item in results.values()}
    overall = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    return {
        "benchmark": "serve_read_routes_p95_gate",
        "fixture": {
            "concepts": 2_000,
            "graph_nodes": 1_000,
            "graph_edges": 999,
        },
        "routes": results,
        "samples_per_route": SAMPLES_PER_ROUTE,
        "warmup_per_route": WARMUP_PER_ROUTE,
        "status": overall,
        "target_p95_ms": TARGET_P95_MS,
        "fail_p95_ms": FAIL_P95_MS,
    }


def main() -> int:
    payload = run_gate()
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 1 if payload["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
