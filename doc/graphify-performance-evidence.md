# Graphify Performance Evidence — Phase 7F Signoff

Date: 2026-05-08
Platform: macOS Darwin 25.4.0, Python 3.13, SQLite 3.51.3

> 2026-05-11 note: the backend parse numbers below are still the parser evidence
> for this fixture. The frontend graph renderer has since moved from SVG to
> `react-force-graph-2d` Canvas. This file no longer claims current Canvas
> frame-time or real large-repo browser signoff.

## Backend Parse Performance (parse_graph_json)

| Dataset | Nodes | Links | File Size | mean | p50 | p95 |
|---------|-------|-------|-----------|------|-----|-----|
| large (benchmark) | 500 | 1,500 | 217 KB | 10.7ms | 10.7ms | 11.2ms |
| **real repo** | **1,785** | **3,775** | **2.0 MB** | **119.5ms** | **117.9ms** | **128.7ms** |
| xlarge (benchmark) | 5,000 | 15,000 | 2.2 MB | 115.7ms | 115.7ms | 124.1ms |

Iterations: 10 per dataset.

## Memory (xlarge 5000-node)

- Current allocation: 13,860 KB
- Peak allocation: 24,101 KB

## Parser Safety Limits

- File size cap: 50 MiB (`parser.py`)
- Edge cap: 50,000 (`parser.py`)
- Dedup + dangling removal + sanitization applied
- `graph_sha256` provenance computed per parse

## Frontend Handling

- `LARGE_GRAPH_THRESHOLD = 150`: large graphs default to List view
- Manual "Full graph" toggle available for Graph view
- Current product graph view uses Canvas through `react-force-graph-2d`
- Canvas graph has a semantic list fallback for accessibility
- Current real data (1785 nodes) still defaults to List view; Canvas frame-time needs a separate browser signoff

## API Response

- `GET /api/graph/concepts` returns paginated data (default limit 500)
- `?limit=2000` for full dataset support
- Sanitized output strips home/system path prefixes

## Verdict

**PASS for backend parser budget** — 5000-node parse completes in <130ms with <25MB peak memory. Real repo (1785 nodes) remains within the parser budget. Frontend still degrades to List view for large graphs, but current Canvas rendering performance should be signed off separately.
