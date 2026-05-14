# AhaDiff v1.0 Performance Baseline (R5)

> Reran 2026-04-28 on macOS Darwin 25.4.0. All timings are wall-clock.

## Measurement Protocol Status

This file is still a v1.0 planning baseline, but the Phase 0 benchmark runner is now in the repo.

- **Reproducible now**: `bench_cli_startup.py`, `bench_diff_parse.py`, `bench_sqlite_queries.py`, `bench_bundle_size.sh`, `bench_serve_read_routes.py`, and `run_all.sh`.
- **Latest aggregate artifact**: `run_all.sh` wrote `benchmarks/results/baseline_20260428.json` in this session.
- **Available but state-dependent**: `bench_api_latency.py` is committed, but the latest run in this session returned `skipped` because `ahadiff serve` was not running.
- **Still ad-hoc**: R5.1 concepts pressure test. There is still no committed `bench_concepts_10k.py`.
- **v1.0 gate requirement**: keep extending the committed scripts so they also record commit SHA, hardware/OS, Python/Node/uv/pnpm versions, sample count, warmup count, DB state, and whether serve was started empty or with fixtures.

Current committed commands:

```bash
uv run python benchmarks/scripts/bench_cli_startup.py
uv run python benchmarks/scripts/bench_diff_parse.py
uv run python benchmarks/scripts/bench_sqlite_queries.py
uv run python benchmarks/scripts/bench_serve_read_routes.py
bash benchmarks/scripts/bench_bundle_size.sh
AHADIFF_BENCH_PYTHON="$(pwd)/.venv/bin/python" bash benchmarks/scripts/run_all.sh
```

Current state of the missing pieces:

```bash
# Still missing
uv run python benchmarks/scripts/bench_concepts_10k.py

# Already committed, but only useful when a local server is up
uv run python benchmarks/scripts/bench_api_latency.py
```

---

## R5.1 Concepts 10k Pressure Test

**Reproduction status**: ad-hoc baseline. Needs a committed script before use as a regression gate.

| Metric | Value |
|--------|-------|
| File size (10k entries) | 2.18 MB |
| Load time (raw `json.loads` per line) | **133.0 ms** |
| Memory per dict (shallow `sys.getsizeof`) | 272 bytes |
| Estimated total (dicts only) | ~2.59 MB |
| Unique key set build (`set()`) | 18.0 ms |
| Parent filter (list comprehension) | 2.0 ms |
| Ancestry BFS (single chain) | 2.1 ms |

**Assessment**: 10k concepts load in ~133 ms, well within interactive budget. No bottleneck at current scale. At 100k entries (~22 MB), expect ~1.3 s -- may need streaming/pagination for frontend.

---

## R5.2 Diff Parse Performance

**Reproduction status**: reproducible in this session via `uv run python benchmarks/scripts/bench_diff_parse.py`.

### Benchmark Fixtures (30 patches, all small ~320 bytes)

| Fixture | Size | Lines | Parse (line scan) |
|---------|------|-------|-------------------|
| diff.patch (largest) | 327 B | 12 | 0.01 ms |

### Synthetic Stress Test (1000 hunks)

| Metric | Value |
|--------|-------|
| Synthetic diff size | 102,570 bytes (100 KB tier example) |
| Lines | 2,630 |
| Hunks | 1,000 |
| `parse_unified_diff()` total time (100 KB tier, 40 iterations) | **189.667 ms** |
| Bytes per second | **21,631,606 B/s** |
| Lines per second | **554,657 lines/s** |

**Assessment**: The committed script is now real and reproducible. On the current machine the diff parser is comfortably fast for the shipped synthetic tiers; the next missing piece is a committed concepts-pressure script so this section no longer mixes synthetic parser timing with ad-hoc data.

---

## R5.3 Serve API Response Times (127.0.0.1, script default port 18321)

**Reproduction status**: script exists, but the latest run in this session was `skipped` because serve was not started.

Latest script result:

```json
{
  "benchmark": "api_latency",
  "host": "127.0.0.1",
  "port": 18321,
  "reason": "serve_not_running",
  "status": "skipped"
}
```

**Assessment**: The code path is now script-backed, but we still need a standardized "start serve, then measure" harness before treating API latency as a regression gate.

## R5.3b Serve Read-Route Fixture Gate

**Reproduction status**: committed self-contained benchmark script. It uses Starlette `TestClient`
with a generated local fixture, so it does not require a separately running `ahadiff serve`.

Current command:

```bash
uv run python benchmarks/scripts/bench_serve_read_routes.py
```

The gate measures five read routes over a generated fixture:

- `GET /api/runs`
- `GET /api/concepts`
- `GET /api/graph/concepts`
- `GET /api/search`
- `GET /api/ratchet/transparency`

It records 5 warmups and 30 samples per route. p95 over 50 ms is `warn`; p95 over 500 ms,
HTTP errors, or invalid response shape are `fail`. `run_all.sh` now treats `fail` and
`error` from this script as release-blocking. This is a useful local read-route regression
gate, but it is still not the same thing as an end-to-end browser or externally hosted API
latency benchmark.

---

## R5.4 Frontend Bundle Analysis

**Reproduction status**: reproducible with `bash benchmarks/scripts/bench_bundle_size.sh`.

| Asset | Raw | Gzip | Brotli |
|-------|-----|------|--------|
| `dist/assets/index-CyU3aUp9.js` | 298.21 KB | 91.54 KB | not recorded |
| `dist/assets/index-B0D4LQrU.css` | 63.83 KB | 11.65 KB | not recorded |
| `dist/index.html` | 2.21 KB | 1.15 KB | not recorded |
| **Total written bytes** | **365,956 B** | build output only | not recorded |

**Assessment**: The bundle is still a single JS chunk and still reasonable for a local-first app. The important change here is that the measurement is now repeatable through the committed script instead of living only in an ad-hoc shell transcript.

---

## R5.5 CLI Cold Start

**Reproduction status**: reproducible in this session via `uv run python benchmarks/scripts/bench_cli_startup.py`.

| Metric | Value |
|--------|-------|
| Command | `.venv/bin/python3 -m ahadiff --version` |
| Runs | 10 |
| Mean | **163.289 ms** |
| Min | **156.396 ms** |
| p50 | **160.578 ms** |
| p95 | **170.687 ms** |

**Assessment**: The cold-start script now measures the thing users actually feel: `python -m ahadiff --version`. The latest standalone rerun in this session is ~163 ms mean on this machine. The aggregate `run_all.sh` artifact also landed successfully, but its internal rerun should be treated as a separate sample, not as a long-term promise.

---

## Identified Bottlenecks for v1.0

| Priority | Bottleneck | Current | Target | Mitigation |
|----------|-----------|---------|--------|------------|
| P1 | CLI cold start | 163.289 ms mean | <150 ms | Keep pushing lazy imports and avoid loading heavy modules on `--version` / help paths |
| P2 | Serve API latency gate | Latest script run skipped | reproducible p50/p95 | Add a standard serve-start harness for `bench_api_latency.py` |
| P2 | Concepts at 100k scale | not rerun in this session | <200 ms | Add a committed `bench_concepts_10k.py` before treating this as a tracked gate |
| P3 | JS bundle single chunk | 91.54 KB gzip JS | smaller initial chunk | Route-based code splitting when it is worth the complexity |
