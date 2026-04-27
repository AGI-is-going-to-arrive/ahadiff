#!/usr/bin/env python3
from __future__ import annotations

import http.client
import json
import socket
import statistics
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

HOST = "127.0.0.1"
PORT = 18321
SAMPLES_PER_ENDPOINT = 30
ENDPOINTS = (
    "/api/auth/token",
    "/api/runs",
    "/api/concepts",
    "/api/ratchet/history",
    "/api/config",
)


def _percentile(samples: list[float], percentile: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _probe_server() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


def _request_once(path: str) -> dict[str, Any]:
    connection = http.client.HTTPConnection(HOST, PORT, timeout=5.0)
    try:
        started = time.perf_counter()
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        body = response.read()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "body_bytes": len(body),
            "elapsed_ms": elapsed_ms,
            "status_code": response.status,
        }
    finally:
        connection.close()


def _benchmark_endpoint(path: str) -> dict[str, Any]:
    latencies_ms: list[float] = []
    status_counts: dict[str, int] = {}
    body_bytes: list[int] = []

    for _ in range(SAMPLES_PER_ENDPOINT):
        result = _request_once(path)
        latencies_ms.append(result["elapsed_ms"])
        body_bytes.append(result["body_bytes"])
        key = str(result["status_code"])
        status_counts[key] = status_counts.get(key, 0) + 1

    return {
        "http_status_counts": status_counts,
        "metrics": {
            "mean_ms": round(statistics.fmean(latencies_ms), 3),
            "p50_ms": round(_percentile(latencies_ms, 0.50), 3),
            "p95_ms": round(_percentile(latencies_ms, 0.95), 3),
            "p99_ms": round(_percentile(latencies_ms, 0.99), 3),
        },
        "response_bytes": {
            "max": max(body_bytes),
            "mean": round(statistics.fmean(body_bytes), 1),
            "min": min(body_bytes),
        },
        "samples": SAMPLES_PER_ENDPOINT,
        "status": "ok",
    }


def main() -> dict[str, Any]:
    if not _probe_server():
        return {
            "benchmark": "api_latency",
            "host": HOST,
            "port": PORT,
            "reason": "serve_not_running",
            "status": "skipped",
        }

    endpoint_results: dict[str, Any] = {}
    overall_status = "ok"
    for path in ENDPOINTS:
        key = f"GET {path}"
        try:
            endpoint_results[key] = _benchmark_endpoint(path)
        except Exception as exc:  # pragma: no cover - defensive JSON fallback
            overall_status = "partial"
            endpoint_results[key] = {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "status": "error",
            }

    return {
        "benchmark": "api_latency",
        "endpoints": endpoint_results,
        "host": HOST,
        "port": PORT,
        "samples_per_endpoint": SAMPLES_PER_ENDPOINT,
        "status": overall_status,
        "working_directory": str(REPO_ROOT),
    }


if __name__ == "__main__":
    try:
        _emit(main())
    except Exception as exc:  # pragma: no cover - defensive JSON fallback
        _emit(
            {
                "benchmark": "api_latency",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "status": "error",
            }
        )
